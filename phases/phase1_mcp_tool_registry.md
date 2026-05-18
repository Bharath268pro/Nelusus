# Phase 1 — MCP Tool Registry

## 1. Architecture Explanation
The Foundation of an Enterprise MCP Platform is its **Tool Registry**. The LLM never communicates with APIs directly; it only outputs structured requests indicating which registered "tool" it wants to execute. 

The Tool Registry serves three critical functions:
1. **Discovery:** It exposes `/api/v1/mcp/tools` returning strict JSON schemas (OpenAPI/JSON Schema Draft-07) representing what the agent *can* do.
2. **Validation:** Before any tool is executed, the registry ensures the payload matches the exact schema requirements. 
3. **Dispatch:** It routes a validated `ToolCallRequest` to the correct internal Python function (the connector) asynchronously.

In an enterprise setup, this registry is decoupled from the LLM execution loop. Tools are dynamically loaded (often from a database or a plugin directory) rather than hardcoded, allowing different tenants to see different subsets of tools based on their subscription tier or permissions.

## 2. Folder Structure
We enforce a strict boundary between HTTP transport (`routes`), data contracts (`models`), and business logic (`services`).

```text
backend/app/
├── main.py                  # FastAPI application setup
├── models/
│   └── mcp_registry.py      # Pydantic schemas for Tool metadata and Tool calls
├── routes/
│   └── mcp.py               # Discovery and Execution endpoints
└── services/
    └── registry_engine.py   # Dynamic tool loading and dispatch logic
```

## 3. Exact Code Implementation

### A. Data Contracts (`models/mcp_registry.py`)
We use Pydantic to strictly define what a tool looks like and what a tool execution request requires.

```python
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class ToolSchema(BaseModel):
    """JSON Schema definition for tool arguments"""
    type: str = "object"
    properties: Dict[str, Any]
    required: List[str] = Field(default_factory=list)

class ToolDefinition(BaseModel):
    """Metadata exposed to the LLM for discovery"""
    name: str = Field(..., description="Unique identifier e.g., 'salesforce.get_account'")
    description: str = Field(..., description="Clear explanation of what the tool does")
    inputSchema: ToolSchema
    version: str = "1.0.0"

class ToolCallRequest(BaseModel):
    """Payload sent by the LLM (or orchestrator) to execute a tool"""
    tool_name: str
    arguments: Dict[str, Any]

class ToolCallResponse(BaseModel):
    """Standardized response from tool execution"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
```

### B. Registry Engine (`services/registry_engine.py`)
This service manages the lifecycle of tools. It registers them, exposes their metadata, and routes execution calls safely.

```python
import logging
from typing import Any, Callable, Dict, List
from app.models.mcp_registry import ToolCallRequest, ToolCallResponse, ToolDefinition

logger = logging.getLogger(__name__)

class ToolRegistryEngine:
    def __init__(self):
        # Maps tool_name -> (ToolDefinition, async_callable)
        self._tools: Dict[str, tuple[ToolDefinition, Callable]] = {}

    def register_tool(self, definition: ToolDefinition, handler: Callable):
        """Register a new tool into the MCP ecosystem."""
        if definition.name in self._tools:
            logger.warning(f"Overwriting existing tool: {definition.name}")
        self._tools[definition.name] = (definition, handler)
        logger.info(f"Registered tool: {definition.name}")

    def list_tools(self) -> List[ToolDefinition]:
        """Return all available tools for LLM discovery."""
        return [defn for defn, _ in self._tools.values()]

    async def execute_tool(self, request: ToolCallRequest) -> ToolCallResponse:
        """Route the execution request to the specific handler."""
        if request.tool_name not in self._tools:
            return ToolCallResponse(success=False, error=f"Tool '{request.tool_name}' not found")
        
        _, handler = self._tools[request.tool_name]
        
        try:
            # Execute the actual Python function asynchronously
            result = await handler(**request.arguments)
            return ToolCallResponse(success=True, data=result)
        except TypeError as e:
            # Catch schema mismatch (e.g. LLM hallucinates an argument)
            logger.error(f"Schema violation in {request.tool_name}: {e}")
            return ToolCallResponse(success=False, error=f"Invalid arguments: {e}")
        except Exception as e:
            logger.error(f"Tool {request.tool_name} execution failed: {e}")
            return ToolCallResponse(success=False, error=str(e))

# Global singleton for FastAPI injection
registry = ToolRegistryEngine()
```

### C. FastAPI Routes (`routes/mcp.py`)
The HTTP layer. This is what the Orchestrator/Gateway hits.

```python
from fastapi import APIRouter, Depends, HTTPException
from app.models.mcp_registry import ToolCallRequest, ToolCallResponse, ToolDefinition
from app.services.registry_engine import registry, ToolRegistryEngine

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])

def get_registry() -> ToolRegistryEngine:
    return registry

@router.get("/tools", response_model=list[ToolDefinition])
async def discover_tools(reg: ToolRegistryEngine = Depends(get_registry)):
    """LLM calls this to figure out what it can do."""
    return reg.list_tools()

@router.post("/execute", response_model=ToolCallResponse)
async def execute_tool(
    request: ToolCallRequest, 
    reg: ToolRegistryEngine = Depends(get_registry)
):
    """LLM (via Orchestrator) posts here to trigger action."""
    return await reg.execute_tool(request)
```

## 4. Security Reasoning
- **Schema Enforcement:** By relying on `TypeError` unpacking (`**request.arguments`) against strongly typed async handlers, we ensure the LLM cannot inject arbitrary `kwargs`.
- **Abstraction:** The LLM does not know *how* `salesforce.get_account` works. It has no access to the HTTP client, API tokens, or headers. It merely requests intent, and the Python backend controls the execution.
- **Surface Area Reduction:** Only tools explicitly added via `register_tool()` are executable.

## 5. Scaling Reasoning
- **Async First:** Tools are executed via `await handler(...)`. This prevents the FastAPI event loop from blocking while a tool makes a 5-second network request to Salesforce.
- **Stateless Dispatch:** The `ToolRegistryEngine` maintains no state about the user or workflow. It is a pure function mapping `(tool_name, args) -> result`. This means you can run 50 copies of this FastAPI pod behind a load balancer safely.

## 6. Common Production Pitfalls
- **Sync Blocking:** Registering a synchronous function (e.g., `requests.get`) as a tool handler will block the ASGI worker thread, causing massive latency spikes across the entire API under load.
- **Schema Drift:** If the `ToolDefinition.inputSchema` tells the LLM an argument is optional, but the Python `handler` enforces it as required, the LLM will fail repeatedly in a loop.

## 7. Enterprise Best Practices
- **Namespacing:** Always namespace tools (e.g., `github.create_pr`, `salesforce.update_lead`) to prevent collisions as the registry grows to 100+ tools.
- **Description Quality:** The `description` field is injected directly into the LLM prompt. Production systems treat tool descriptions as prompt engineering. Be explicitly clear (e.g., *"Fetches a user account. Requires a 18-character Salesforce ID"*).

## 8. Step-by-Step Setup Instructions
1. Save the above snippets into their respective folder structure.
2. In your `main.py`, include the router: `app.include_router(mcp.router)`
3. Create a dummy tool to test the registry:
```python
# In main.py, before startup:
async def dummy_weather(location: str):
    return {"temp": 72, "location": location}

registry.register_tool(
    ToolDefinition(
        name="weather.get",
        description="Get weather for a location",
        inputSchema={"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]}
    ),
    dummy_weather
)
```

## 9. Testing Instructions
Boot your FastAPI server:
```bash
uvicorn app.main:app --reload
```

Test Discovery:
```bash
TOKEN=$(PYTHONPATH=. /home/bharath/Documents/Nelusus/venv/bin/python -c "from app.services import AuthenticationService; print(AuthenticationService.create_token(user_id='user123', email='test@example.com', scopes=['mcp:execute']))")

curl -H "Authorization: Bearer $TOKEN" http://localhost:8005/api/v1/mcp/tools

```

Test Execution:
```bash
curl -X POST http://localhost:8005/api/v1/mcp/execute \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"tool_name": "weather.get", "arguments": {"location": "San Francisco"}}'


## 10. Example Requests / Responses

**Discovery Response:**
```json
[
  {
    "name": "weather.get",
    "description": "Get weather for a location",
    "inputSchema": {
      "type": "object",
      "properties": {
        "location": {
          "type": "string"
        }
      },
      "required": [
        "location"
      ]
    },
    "version": "1.0.0"
  }
]
```

**Execution Response:**
```json
{
  "success": true,
  "data": {
    "temp": 72,
    "location": "San Francisco"
  },
  "error": null
}
```

---
**Status:** Phase 1 complete. Awaiting confirmation to proceed to Phase 2 (Authentication + Authorization).
