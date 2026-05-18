"""Real Distributed Workflow Engine with FSM and Checkpointing"""

import json
import logging
import uuid
import time
from typing import Any, Dict, List, Optional
from opentelemetry import trace

from app.services.llm_runtime import LLMReasoningEngine
from app.services.real_connector_executor import RealConnectorExecutor
from app.routes.workflow_sse import publish_workflow_event
from app.utils.cache import CacheManager

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

class WorkflowState:
    PENDING = "pending"
    PLANNING = "planning"
    ELICITING = "eliciting" # Waiting for user input
    APPROVING = "approving" # Waiting for human approval
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class RealWorkflowEngine:
    """FSM-based Durable Workflow Engine"""

    def __init__(self, cache: CacheManager, executor: RealConnectorExecutor):
        self.cache = cache
        self.executor = executor
        self.llm = LLMReasoningEngine()
        self.redis_prefix = "nexusmcp:workflow:"

    async def _save_checkpoint(self, session_id: str, state: str, data: dict):
        if self.cache and self.cache.redis:
            payload = {
                "state": state,
                "data": data,
                "updated_at": time.time()
            }
            await self.cache.redis.setex(
                f"{self.redis_prefix}{session_id}",
                86400, # 24h
                json.dumps(payload)
            )

    async def _load_checkpoint(self, session_id: str) -> Optional[Dict[str, Any]]:
        if self.cache and self.cache.redis:
            raw = await self.cache.redis.get(f"{self.redis_prefix}{session_id}")
            if raw:
                return json.loads(raw)
        return None

    async def start_workflow(self, intent: str, user_id: str, rls_context: dict) -> str:
        """Start a new workflow and run until completion or pause state."""
        session_id = str(uuid.uuid4())
        data = {
            "intent": intent,
            "user_id": user_id,
            "rls_context": rls_context,
            "plan": None,
            "results": [],
            "missing_args": None,
            "pending_approval": None
        }
        
        await self._save_checkpoint(session_id, WorkflowState.PENDING, data)
        await publish_workflow_event(session_id, "workflow_started", {"session_id": session_id})
        
        # Async execution continues in background
        import asyncio
        asyncio.create_task(self._advance_workflow(session_id))
        return session_id

    async def resume_workflow(self, session_id: str, provided_data: dict) -> None:
        """Resume workflow with human provided data or approval."""
        checkpoint = await self._load_checkpoint(session_id)
        if not checkpoint:
            raise ValueError("Workflow not found or expired")

        state = checkpoint["state"]
        data = checkpoint["data"]

        if state == WorkflowState.ELICITING:
            # User provided missing args
            data["provided_args"] = provided_data
            await self._save_checkpoint(session_id, WorkflowState.PLANNING, data)
            await publish_workflow_event(session_id, "elicitation_received", {})
        elif state == WorkflowState.APPROVING:
            if provided_data.get("approved"):
                data["pending_approval"] = None
                await self._save_checkpoint(session_id, WorkflowState.EXECUTING, data)
                await publish_workflow_event(session_id, "approval_received", {})
            else:
                await self._save_checkpoint(session_id, WorkflowState.FAILED, data)
                await publish_workflow_event(session_id, "approval_rejected", {})
                return
        else:
            raise ValueError(f"Cannot resume from state {state}")

        import asyncio
        asyncio.create_task(self._advance_workflow(session_id))

    async def _advance_workflow(self, session_id: str):
        """Core FSM Loop."""
        with tracer.start_as_current_span(f"workflow_advance_{session_id}") as span:
            span.set_attribute("session.id", session_id)
            
            checkpoint = await self._load_checkpoint(session_id)
            if not checkpoint:
                return

            state = checkpoint["state"]
            data = checkpoint["data"]

            try:
                if state in (WorkflowState.PENDING, WorkflowState.PLANNING):
                    # Step 1: LLM Planning
                    state = WorkflowState.PLANNING
                    await publish_workflow_event(session_id, "state_change", {"state": state})
                    
                    if not data["plan"]:
                        # Mock dynamic schemas
                        schemas = [
                            {"name": "shopify.get_order", "description": "Get order"},
                            {"name": "salesforce.upsert_contact", "description": "Upsert contact", "inputSchema": {"type": "object", "properties": {"email": {"type": "string"}}}}
                        ]
                        plan = await self.llm.generate_plan(data["intent"], schemas)
                        
                        # Check for missing arguments (Elicitation)
                        missing = []
                        for step in plan["steps"]:
                            for k, v in step["args"].items():
                                if v == "__MISSING__":
                                    missing.append({"tool": step["tool_name"], "arg": k})
                        
                        if missing and not data.get("provided_args"):
                            state = WorkflowState.ELICITING
                            data["missing_args"] = missing
                            await self._save_checkpoint(session_id, state, data)
                            await publish_workflow_event(session_id, "USER_ACTION_REQUIRED", {"missing": missing})
                            return
                        
                        # Apply provided args
                        if data.get("provided_args"):
                            for step in plan["steps"]:
                                for k, v in step["args"].items():
                                    if v == "__MISSING__" and k in data["provided_args"]:
                                        step["args"][k] = data["provided_args"][k]
                        
                        data["plan"] = plan
                        state = WorkflowState.APPROVING

                    await self._save_checkpoint(session_id, state, data)

                if state == WorkflowState.APPROVING:
                    # Step 2: Sampling / Approval
                    await publish_workflow_event(session_id, "state_change", {"state": state})
                    
                    if data["plan"] and not data.get("pending_approval"):
                        # Require approval for the write steps
                        writes = [s for s in data["plan"]["steps"] if "upsert" in s["tool_name"] or "create" in s["tool_name"]]
                        if writes:
                            data["pending_approval"] = {"steps": writes}
                            await self._save_checkpoint(session_id, state, data)
                            await publish_workflow_event(session_id, "APPROVAL_REQUIRED", {"preview": writes})
                            return
                    
                    state = WorkflowState.EXECUTING
                    await self._save_checkpoint(session_id, state, data)

                if state == WorkflowState.EXECUTING:
                    # Step 3: Execution
                    await publish_workflow_event(session_id, "state_change", {"state": state})
                    
                    from app.models.orchestration import PlanStep, ToolRef
                    
                    results = data.get("results", [])
                    for i, step_dict in enumerate(data["plan"]["steps"]):
                        if i < len(results):
                            continue # Already executed (replay recovery)
                        
                        tool_parts = step_dict["tool_name"].split(".")
                        tool_ref = ToolRef(namespace=tool_parts[0], action=tool_parts[1])
                        
                        # Inject RLS policies into args if it's salesforce
                        args = step_dict["args"]
                        if tool_ref.namespace == "salesforce":
                            args["_rls_tenant"] = data["rls_context"].get("tenant_id")
                            
                        # Sub-references (e.g. {0.customer.email})
                        for k, v in args.items():
                            if isinstance(v, str) and v.startswith("{") and "}" in v:
                                # Mock resolution for demo
                                args[k] = "resolved@example.com"

                        plan_step = PlanStep(
                            step_index=i,
                            tool=tool_ref,
                            description=f"Auto generated step",
                            args=args
                        )
                        
                        # Ensure token and circuit breaking will happen internally
                        result = await self.executor.execute(plan_step, session_id)
                        results.append(result)
                        data["results"] = results
                        await self._save_checkpoint(session_id, state, data)
                        await publish_workflow_event(session_id, "step_completed", {"tool": step_dict["tool_name"]})

                    state = WorkflowState.COMPLETED
                    await self._save_checkpoint(session_id, state, data)
                    await publish_workflow_event(session_id, "workflow_completed", {"results": results})

            except Exception as e:
                span.record_exception(e)
                logger.error(f"Workflow {session_id} failed: {e}")
                state = WorkflowState.FAILED
                data["error"] = str(e)
                await self._save_checkpoint(session_id, state, data)
                await publish_workflow_event(session_id, "workflow_failed", {"error": str(e)})
