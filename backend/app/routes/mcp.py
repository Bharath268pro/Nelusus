"""JSON-RPC 2.0 MCP gateway routes"""

import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, HTTPException, Depends, Response
from fastapi.responses import StreamingResponse
import json
from app.config import Settings, get_settings
from app.models.jsonrpc import (
    JSONRPCRequest,
    Identity,
    ToolCallRequest,
    ToolListRequest,
)
from app.services.jsonrpc_handler import (
    JSONRPCHandler,
    ToolCallHandler,
    ToolListHandler,
)
from app.models.error_codes import create_jsonrpc_error, ErrorCode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["mcp"])

# Initialize handlers
jsonrpc_handler = JSONRPCHandler()
tool_call_handler = ToolCallHandler(jsonrpc_handler)
tool_list_handler = ToolListHandler(jsonrpc_handler)


@router.post("/rpc")
async def handle_jsonrpc(
    request: Request, settings: Settings = Depends(get_settings)
):
    """
    Main JSON-RPC 2.0 endpoint
    
    Accepts:
    - Single JSON-RPC request
    - Batch of JSON-RPC requests (array)
    - Tools/call and tools/list methods
    """
    try:
        # Get identity from middleware
        identity: Optional[Identity] = getattr(request.state, "identity", None)

        # Read request body
        body = await request.body()
        if not body:
            error = create_jsonrpc_error(
                ErrorCode.INVALID_REQUEST,
                data={"reason": "Empty request body"},
            )
            return error.model_dump()

        # Try to parse as single request or batch
        is_batch = False
        requests = jsonrpc_handler.parse_batch_request(body)

        if not requests:
            # Try single request
            parsed_request = jsonrpc_handler.parse_request(body)
            if not parsed_request:
                error = create_jsonrpc_error(
                    ErrorCode.PARSE_ERROR,
                    data={"reason": "Invalid JSON-RPC format"},
                )
                return error.model_dump()
            requests = [parsed_request]
        else:
            is_batch = True
            if len(requests) > settings.jsonrpc_batch_request_max_size:
                error = create_jsonrpc_error(
                    ErrorCode.INVALID_REQUEST,
                    data={
                        "reason": f"Batch size exceeds limit of {settings.jsonrpc_batch_request_max_size}"
                    },
                )
                return error.model_dump()

        # Process requests
        responses = []
        for req in requests:
            response = await _process_single_request(
                req, identity, settings, getattr(request.state, "rls_context", None)
            )
            # Only include response if not a notification (no id)
            if response is not None and req.id is not None:
                responses.append(response)

        # Return response(s)
        if is_batch:
            return [r.model_dump() for r in responses]
        elif responses:
            return responses[0].model_dump()
        else:
            # All requests were notifications
            return {}

    except Exception as e:
        logger.error(f"RPC handler error: {e}")
        error = create_jsonrpc_error(
            ErrorCode.INTERNAL_ERROR,
            data={"reason": "Internal server error"},
        )
        return error.model_dump()


async def _process_single_request(
    request: JSONRPCRequest,
    identity: Optional[Identity],
    settings: Settings,
    rls_context: Optional[Dict] = None,
) -> Optional[Dict[str, Any]]:
    """Process a single JSON-RPC request"""

    # Validate JSON-RPC structure
    if request.jsonrpc != "2.0":
        error = create_jsonrpc_error(
            ErrorCode.INVALID_REQUEST,
            request.id,
            {"reason": "Invalid jsonrpc version"},
        )
        return error

    # Route to appropriate handler
    if request.method == "tools/call":
        try:
            tool_call_req = ToolCallRequest(**request.model_dump())
            response = await tool_call_handler.handle_tool_call(
                tool_call_req, identity, rls_context
            )
            return response.model_dump()
        except Exception as e:
            logger.error(f"Error processing tools/call: {e}")
            error = create_jsonrpc_error(
                ErrorCode.INVALID_PARAMS,
                request.id,
                {"reason": f"Invalid parameters: {str(e)}"},
            )
            return error.model_dump()

    elif request.method == "tools/list":
        try:
            tool_list_req = ToolListRequest(**request.model_dump())
            response = await tool_list_handler.handle_tool_list(tool_list_req, identity)
            return response.model_dump()
        except Exception as e:
            logger.error(f"Error processing tools/list: {e}")
            error = create_jsonrpc_error(
                ErrorCode.INVALID_PARAMS,
                request.id,
                {"reason": f"Invalid parameters: {str(e)}"},
            )
            return error.model_dump()

    else:
        # Method not found
        error = create_jsonrpc_error(
            ErrorCode.METHOD_NOT_FOUND,
            request.id,
            {"method": request.method},
        )
        return error.model_dump()
