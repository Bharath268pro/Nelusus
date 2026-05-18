"""SSE Workflow Streaming Router using sse-starlette"""

import asyncio
import logging
import json
from typing import AsyncGenerator
from fastapi import APIRouter, Request, HTTPException
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])

# In-memory pub/sub for SSE (Production: use Redis PubSub)
WORKFLOW_CHANNELS = {}

async def publish_workflow_event(session_id: str, event_type: str, data: dict):
    """Publish an event to all subscribers of a workflow session."""
    if session_id in WORKFLOW_CHANNELS:
        payload = {"type": event_type, "data": data}
        for queue in WORKFLOW_CHANNELS[session_id]:
            await queue.put(payload)

@router.get("/stream/{session_id}", summary="SSE Stream for Workflow execution")
async def workflow_stream(session_id: str, request: Request):
    """Stream workflow events via Server-Sent Events (SSE)."""
    
    # Initialize channel
    if session_id not in WORKFLOW_CHANNELS:
        WORKFLOW_CHANNELS[session_id] = set()
    
    queue = asyncio.Queue()
    WORKFLOW_CHANNELS[session_id].add(queue)
    
    async def event_generator() -> AsyncGenerator[dict, None]:
        try:
            # Yield initial connection heartbeat
            yield {
                "event": "connected",
                "data": json.dumps({"session_id": session_id, "status": "listening"})
            }
            
            while True:
                # Check for client disconnect
                if await request.is_disconnected():
                    logger.info(f"Client disconnected from SSE stream {session_id}")
                    break
                
                try:
                    # Wait for message with timeout for heartbeat
                    message = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {
                        "event": message["type"],
                        "data": json.dumps(message["data"])
                    }
                except asyncio.TimeoutError:
                    # Heartbeat
                    yield {
                        "event": "ping",
                        "data": json.dumps({"timestamp": asyncio.get_event_loop().time()})
                    }
        finally:
            # Cleanup
            if session_id in WORKFLOW_CHANNELS:
                WORKFLOW_CHANNELS[session_id].discard(queue)
                if not WORKFLOW_CHANNELS[session_id]:
                    del WORKFLOW_CHANNELS[session_id]

    return EventSourceResponse(event_generator())
