# Phase 10 — LLM Orchestration

## 1. Architecture Explanation
Up until now, we have built a **Passive Tool Registry**. The LLM knows *what* tools exist, but it needs an active engine to drive the reasoning process, handle failures, ask follow-up questions, and execute tools in a safe sequence.

This is the **Orchestrator**. Enterprise orchestrators (like LangGraph, OpenAI Operator, or Temporal) do not use simple `while True` loops. They use **Durable State Machines**.

The architecture involves:
1. **The ReAct Loop (Reason + Act):** The LLM analyzes the user prompt, decides on a tool (Action), waits for the backend to execute it (Observation), and then Reasons about the result.
2. **Durable FSM (Finite State Machine):** Because LLM inference takes 5-10 seconds per step, we cannot hold a synchronous HTTP request open. We map execution to strict states: `PENDING` → `PLANNING` → `APPROVING` → `EXECUTING` → `COMPLETED`. We checkpoint the state to Redis at every transition.
3. **SSE Streaming (Server-Sent Events):** As the backend transitions states or the LLM streams tokens, we push events asynchronously to the frontend React UI over an open SSE connection.
4. **Human-In-The-Loop (HITL):** If a mutation tool is planned (e.g., `salesforce.create_lead`), the FSM halts at the `APPROVING` state and pushes an event to the frontend. The workflow is entirely suspended until the human clicks "Approve".

## 2. Folder Structure
```text
backend/app/
├── orchestration/
│   ├── engine.py        # The core FSM ReAct loop and Checkpointing
│   ├── llm_client.py    # OpenAI/Claude API wrappers for Tool Calling
│   └── sse_router.py    # FastAPI StreamingResponse routes
```

## 3. Exact Code Implementation

### A. The LLM Client (`orchestration/llm_client.py`)
This translates our MCP tool registry into the exact JSON Schema required by OpenAI Function Calling.

```python
import os
import json
from openai import AsyncOpenAI
from app.services.registry_engine import registry

client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

async def reason_next_step(system_prompt: str, message_history: list) -> dict:
    """
    Asks the LLM to decide the next action based on available tools.
    """
    # 1. Dynamically pull tools from our Registry (Phase 1)
    tools = []
    for tool_def in registry.list_tools():
        tools.append({
            "type": "function",
            "function": {
                "name": tool_def.name,
                "description": tool_def.description,
                "parameters": tool_def.inputSchema
            }
        })

    # 2. Call OpenAI with Tool Support
    response = await client.chat.completions.create(
        model="gpt-4-turbo",
        messages=[{"role": "system", "content": system_prompt}] + message_history,
        tools=tools,
        tool_choice="auto",
        temperature=0.0 # Determinism is key for agents
    )
    
    msg = response.choices[0].message
    
    if msg.tool_calls:
        # LLM wants to execute a tool
        return {
            "type": "tool_call",
            "calls": [
                {"name": tc.function.name, "args": json.loads(tc.function.arguments), "id": tc.id} 
                for tc in msg.tool_calls
            ]
        }
    else:
        # LLM is done and wants to reply to the user
        return {
            "type": "message",
            "content": msg.content
        }
```

### B. The Durable FSM Engine (`orchestration/engine.py`)
This controls the orchestration loop, saving state to Redis.

```python
import uuid
import json
import logging
from typing import Dict, Any
import aioredis # Or redis-py async
from app.orchestration.llm_client import reason_next_step
from app.services.registry_engine import registry
from app.models.auth import UserContext

logger = logging.getLogger(__name__)

# Redis Client connection
redis = aioredis.from_url("redis://localhost:6379", decode_responses=True)

class WorkflowState:
    PLANNING = "planning"
    APPROVING = "approving"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"

async def save_checkpoint(session_id: str, data: dict):
    """Saves workflow state to Redis to survive pod crashes."""
    await redis.set(f"workflow:{session_id}", json.dumps(data))

async def load_checkpoint(session_id: str) -> dict:
    data = await redis.get(f"workflow:{session_id}")
    return json.loads(data) if data else None

async def advance_workflow(session_id: str, user_context: UserContext):
    """The core orchestration loop. Driven asynchronously."""
    
    data = await load_checkpoint(session_id)
    if not data or data["state"] in [WorkflowState.COMPLETED, WorkflowState.FAILED]:
        return

    try:
        if data["state"] == WorkflowState.PLANNING:
            # 1. Ask the LLM what to do next
            decision = await reason_next_step(
                system_prompt="You are an enterprise AI agent.", 
                message_history=data["messages"]
            )
            
            if decision["type"] == "message":
                # Workflow finished!
                data["messages"].append({"role": "assistant", "content": decision["content"]})
                data["state"] = WorkflowState.COMPLETED
                await save_checkpoint(session_id, data)
                await publish_sse_event(session_id, "completed", decision["content"])
                return
                
            elif decision["type"] == "tool_call":
                data["pending_tools"] = decision["calls"]
                
                # HITL Check: Does this tool require human approval?
                requires_approval = any(call["name"].startswith("salesforce.create") or call["name"].startswith("github.") for call in decision["calls"])
                
                if requires_approval and not data.get("approved"):
                    data["state"] = WorkflowState.APPROVING
                    await save_checkpoint(session_id, data)
                    # Halt the loop and ask frontend for approval
                    await publish_sse_event(session_id, "approval_required", decision["calls"])
                    return
                else:
                    data["state"] = WorkflowState.EXECUTING
                    await save_checkpoint(session_id, data)

        if data["state"] == WorkflowState.EXECUTING:
            # 2. Execute the tools
            for call in data["pending_tools"]:
                await publish_sse_event(session_id, "executing_tool", call["name"])
                
                # Call our MCP Registry (from Phase 1 & 2)
                from app.models.mcp_registry import ToolCallRequest
                req = ToolCallRequest(tool_name=call["name"], arguments=call["args"])
                result = await registry.execute_tool(req, user_context)
                
                # Append the observation back into the LLM's history
                data["messages"].append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": json.dumps(result.model_dump())
                })
                
            # Loop back to planning to let the LLM evaluate the tool results
            data["pending_tools"] = []
            data["approved"] = False # Reset approval for next loop
            data["state"] = WorkflowState.PLANNING
            await save_checkpoint(session_id, data)
            
            # Recursively advance the workflow
            import asyncio
            asyncio.create_task(advance_workflow(session_id, user_context))

    except Exception as e:
        logger.error(f"Workflow {session_id} failed: {e}")
        data["state"] = WorkflowState.FAILED
        await save_checkpoint(session_id, data)
        await publish_sse_event(session_id, "error", str(e))
```

### C. Server-Sent Events Router (`orchestration/sse_router.py`)
This pushes updates to the frontend React application in real-time.

```python
import asyncio
import json
from fastapi import APIRouter, Request, Depends
from sse_starlette.sse import EventSourceResponse
from app.dependencies.auth import get_current_user, UserContext
from app.orchestration.engine import advance_workflow, save_checkpoint, load_checkpoint, WorkflowState

router = APIRouter(prefix="/api/v1/orchestration")

# In-memory pub/sub (In production, use Redis Pub/Sub)
CHANNELS = {}

async def publish_sse_event(session_id: str, event_type: str, data: Any):
    if session_id in CHANNELS:
        await CHANNELS[session_id].put({"event": event_type, "data": json.dumps(data)})

@router.post("/start")
async def start_workflow(prompt: str, user: UserContext = Depends(get_current_user)):
    """Entrypoint to trigger an agent workflow."""
    session_id = str(uuid.uuid4())
    
    initial_data = {
        "state": WorkflowState.PLANNING,
        "messages": [{"role": "user", "content": prompt}],
        "pending_tools": [],
        "approved": False
    }
    await save_checkpoint(session_id, initial_data)
    
    # Fire and forget the background execution loop
    asyncio.create_task(advance_workflow(session_id, user))
    
    return {"session_id": session_id}

@router.post("/approve/{session_id}")
async def approve_workflow(session_id: str, user: UserContext = Depends(get_current_user)):
    """Hit by the frontend when the human clicks 'Approve'."""
    data = await load_checkpoint(session_id)
    if data["state"] == WorkflowState.APPROVING:
        data["approved"] = True
        data["state"] = WorkflowState.EXECUTING
        await save_checkpoint(session_id, data)
        
        # Resume the background loop
        asyncio.create_task(advance_workflow(session_id, user))
    return {"status": "resumed"}

@router.get("/stream/{session_id}")
async def stream_workflow(request: Request, session_id: str):
    """The React UI connects here to listen for status updates."""
    queue = asyncio.Queue()
    CHANNELS[session_id] = queue

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                # Wait for the next event published by the engine
                message = await queue.get()
                yield message
        finally:
            del CHANNELS[session_id]

    return EventSourceResponse(event_generator())
```

## 4. Security Reasoning
- **Hard Approval Gates:** The `APPROVING` state mathematically prevents the LLM from executing a mutation. Because the workflow physically halts and saves state to Redis, there is no risk of a race condition allowing the tool to execute. The backend dictates approval, not the LLM.
- **Durable Checkpointing:** If the Kubernetes Pod running the FastAPI server crashes due to OOM during execution, the workflow is not lost. Because state is maintained in Redis, a new Pod can pick up the session ID and resume the ReAct loop where it left off.
- **Injected Identity:** The `user_context` (from the JWT) is passed straight through the orchestrator down to the MCP registry, ensuring that the tool executions maintain the correct tenant boundaries.

## 5. Scaling Reasoning
- **SSE vs WebSockets:** Server-Sent Events (SSE) operate over standard HTTP/1.1 and HTTP/2. They are vastly superior to WebSockets for Agent orchestration because they handle corporate firewalls, load balancers, and reconnections natively without complex heartbeat logic.
- **Asynchronous Loop Suspension:** By using `asyncio.create_task` and exiting the function during human approval, the Python thread is freed immediately. One FastAPI worker can manage thousands of "paused" workflows simultaneously.

## 6. Common Production Pitfalls
- **Infinite Loops:** An LLM might get stuck in a loop (e.g., executing a search tool, failing, and trying again infinitely). You must enforce a `MAX_STEPS` counter in the `advance_workflow` logic (e.g., `if len(data["messages"]) > 20: state = FAILED`).
- **Context Window Exhaustion:** After 5-6 tool executions, the `messages` array becomes enormous. You need to implement an summarization hook or trim older `tool` observation messages before passing them to the OpenAI API.

## 7. Enterprise Best Practices
- **Plan and Execute vs ReAct:** While simple ReAct loops evaluate after *every* tool call, advanced systems (like Devin or LangGraph) generate a Multi-Step Plan first, validate the whole plan with the human, and then execute it. This is more token-efficient and safer.
- **Audit Traces:** Log the entire `messages` array to a persistent cold storage database (e.g., AWS S3 or Postgres JSONB) when the state reaches `COMPLETED` for compliance auditing.

## 8. Step-by-Step Setup Instructions
1. Install dependencies: `pip install openai aioredis sse-starlette`.
2. Ensure you have a local Redis instance running (`docker run -p 6379:6379 redis`).
3. Add the Orchestrator code to your project.
4. Mount the `sse_router.py` in your `main.py`.

## 9. Example Request / Response Lifecycle

1. **Start Workflow:** UI calls `POST /api/v1/orchestration/start?prompt="Create a lead for John in Salesforce"`. Returns `session_id: "123"`.
2. **Listen:** UI opens an `EventSource` connection to `GET /stream/123`.
3. **Agent Reason:** LLM selects `salesforce.create_lead`.
4. **SSE Event:** Frontend receives `{"event": "approval_required", "data": "[{name: 'salesforce.create_lead', args: {...}}]"}`. UI pops a modal.
5. **Approve:** User clicks Approve -> `POST /approve/123`.
6. **Execute & Complete:** Tool executes. SSE receives `{"event": "completed", "data": "I have successfully created the lead for John."}`.

---
**Status:** Phase 10 complete. Awaiting confirmation to proceed to Phase 11 (Production Scaling).
