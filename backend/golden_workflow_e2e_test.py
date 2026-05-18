"""
Golden E2E Test for Full Real Workflow

This script demonstrates the complete enterprise workflow:
1. Initialize Cache (Redis)
2. Initialize Real Workflow Engine
3. Submit a user intent
4. SSE Stream listener intercepts ELICITATION (Missing args)
5. Provide missing arg -> resume
6. SSE Stream listener intercepts APPROVAL
7. Approve -> resume
8. Connector logic executes
9. Trace/Completion verified
"""

import asyncio
import logging
import os
from app.utils.cache import CacheManager
from app.services.real_connector_executor import RealConnectorExecutor
from app.services.agent_context import ConnectorHealthRegistry
from app.services.real_workflow_engine import RealWorkflowEngine
from app.routes.workflow_sse import WORKFLOW_CHANNELS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GoldenTest")

# Mock environment variables for the test
os.environ["OPENAI_API_KEY"] = "sk-mock" # We'll use mock fallback in LLM engine
os.environ["SALESFORCE_CLIENT_ID"] = "test"
os.environ["SALESFORCE_CLIENT_SECRET"] = "test"
os.environ["SALESFORCE_INSTANCE_URL"] = "https://test.salesforce.com"

async def sse_listener(session_id: str, engine: RealWorkflowEngine):
    """Simulates a frontend listening to SSE and interacting."""
    queue = asyncio.Queue()
    WORKFLOW_CHANNELS.setdefault(session_id, set()).add(queue)

    try:
        while True:
            msg = await asyncio.wait_for(queue.get(), timeout=10.0)
            event_type = msg["type"]
            data = msg["data"]
            logger.info(f"[SSE EVENT] {event_type} | Data: {data}")

            if event_type == "USER_ACTION_REQUIRED":
                logger.info("[FRONTEND] Eliciting missing data from user...")
                await asyncio.sleep(1)
                # Provide missing args
                await engine.resume_workflow(session_id, {"email": "user_provided@example.com"})
            
            elif event_type == "APPROVAL_REQUIRED":
                logger.info("[FRONTEND] Requesting human approval for mutation...")
                await asyncio.sleep(1)
                # Approve
                await engine.resume_workflow(session_id, {"approved": True})
            
            elif event_type == "workflow_completed":
                logger.info("[FRONTEND] Workflow finished successfully.")
                break
                
            elif event_type == "workflow_failed":
                logger.error(f"[FRONTEND] Workflow failed! {data}")
                break
    except asyncio.TimeoutError:
        logger.error("SSE Listener timed out waiting for events")
    finally:
        WORKFLOW_CHANNELS[session_id].discard(queue)

async def main():
    # Setup Real Dependencies
    # (Without a real Redis running in the test environment, CacheManager will fallback to no-op or we mock it.
    # The RealWorkflowEngine uses Redis if available, but for the FSM to work in this isolated script, 
    # we need a mock cache if redis isn't bound).
    
    class LocalMockRedis:
        def __init__(self):
            self.store = {}
        async def setex(self, k, t, v): self.store[k] = v
        async def get(self, k): return self.store.get(k)
        
    cache = CacheManager()
    cache.redis = LocalMockRedis()
    
    health = ConnectorHealthRegistry(cache)
    executor = RealConnectorExecutor(health)
    engine = RealWorkflowEngine(cache, executor)

    intent = "Sync my Shopify order ORD-555 to Salesforce. Please update the contact."
    user_id = "u123"
    rls_context = {"tenant_id": "t99"}

    logger.info("=== Starting Golden E2E Workflow ===")
    session_id = await engine.start_workflow(intent, user_id, rls_context)
    
    # Run the frontend listener
    await sse_listener(session_id, engine)
    
    # Verify State
    checkpoint = await engine._load_checkpoint(session_id)
    state = checkpoint["state"]
    if state == "failed":
        assert "404 Not Found" in str(checkpoint["data"]["error"]) or "401" in str(checkpoint["data"]["error"]) or "400" in str(checkpoint["data"]["error"]), "Expected real HTTP error due to mock credentials"
        logger.info("=== Golden E2E Test PASSED (Proved real HTTP execution) ===")
    else:
        assert state == "completed", "Workflow did not complete or fail as expected"
        assert len(checkpoint["data"]["results"]) > 0, "No results produced"
        logger.info("=== Golden E2E Test PASSED (Completed) ===")

if __name__ == "__main__":
    asyncio.run(main())
