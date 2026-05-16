"""JSON-RPC 2.0 protocol handler and request processor"""

import logging
import json
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from app.models.jsonrpc import (
    JSONRPCRequest,
    JSONRPCResult,
    JSONRPCErrorResponse,
    ToolCallRequest,
    ToolCallResult,
    ToolCallResponse,
    ToolContent,
    ToolListRequest,
    ToolListResponse,
    ToolDefinition,
    ToolListResult,
    BatchRequest,
    BatchResponse,
    Identity,
)
from app.models.error_codes import create_jsonrpc_error, ErrorCode
from app.utils.tracing import create_span, add_span_attribute

logger = logging.getLogger(__name__)


class JSONRPCHandler:
    """Handles JSON-RPC 2.0 protocol requests and responses"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse_request(self, data: Union[str, bytes, Dict]) -> Optional[JSONRPCRequest]:
        """Parse incoming JSON-RPC request from raw data"""
        try:
            if isinstance(data, (str, bytes)):
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                parsed = json.loads(data)
            else:
                parsed = data

            # Validate JSON-RPC structure
            if not isinstance(parsed, dict):
                return None

            request = JSONRPCRequest(**parsed)
            return request
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parse error: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Request parsing error: {e}")
            return None

    def parse_batch_request(self, data: Union[str, bytes]) -> Optional[List[JSONRPCRequest]]:
        """Parse a batch of JSON-RPC requests"""
        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            parsed = json.loads(data)

            if not isinstance(parsed, list) or len(parsed) == 0:
                return None

            requests = []
            for item in parsed:
                try:
                    request = JSONRPCRequest(**item)
                    requests.append(request)
                except Exception as e:
                    self.logger.error(f"Error parsing batch item: {e}")
                    # Continue to collect all valid requests
                    continue

            return requests if requests else None
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parse error in batch: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Batch parsing error: {e}")
            return None

    def create_result_response(
        self, request_id: Optional[str | int], result: Any
    ) -> JSONRPCResult:
        """Create a successful JSON-RPC response"""
        return JSONRPCResult(jsonrpc="2.0", result=result, id=request_id)

    def create_error_response(
        self, request_id: Optional[str | int], error_code: ErrorCode, data: Optional[Dict] = None
    ) -> JSONRPCErrorResponse:
        """Create an error JSON-RPC response"""
        return create_jsonrpc_error(error_code, request_id, data)

    def validate_tool_name(self, tool_name: str, pattern: str = r"^[a-z_]+\.[a-z_]+$") -> bool:
        """Validate tool name format"""
        import re

        return bool(re.match(pattern, tool_name))

    def serialize_response(self, response: Union[JSONRPCResult, JSONRPCErrorResponse]) -> str:
        """Serialize response to JSON string"""
        return json.dumps(response.model_dump())

    def serialize_batch_response(self, responses: List[Union[JSONRPCResult, JSONRPCErrorResponse]]) -> str:
        """Serialize batch response to JSON string"""
        return json.dumps([r.model_dump() for r in responses])


class ToolCallHandler:
    """Handles tools/call method requests"""

    def __init__(self, handler: JSONRPCHandler):
        self.handler = handler
        self.logger = logging.getLogger(__name__)

    async def handle_tool_call(
        self,
        request: ToolCallRequest,
        identity: Optional[Identity],
        rls_context: Optional[Dict] = None,
    ) -> Union[ToolCallResponse, JSONRPCErrorResponse]:
        """Handle a tool call request"""
        span = create_span("handler.tool_call", {
            "tool_name": request.params.name,
            "request_id": request.id,
        })

        try:
            # Validate tool name format
            if not self.handler.validate_tool_name(request.params.name):
                self.logger.warning(f"Invalid tool name format: {request.params.name}")
                add_span_attribute(span, "tool.invalid_namespace", True)
                return self.handler.create_error_response(
                    request.id,
                    ErrorCode.INVALID_TOOL_NAMESPACE,
                    {"tool_name": request.params.name},
                )

            # Check identity (should be set by middleware)
            if not identity:
                self.logger.warning("Missing identity for tool call")
                add_span_attribute(span, "tool.identity_missing", True)
                return self.handler.create_error_response(
                    request.id,
                    ErrorCode.TOKEN_VALIDATION_FAILED,
                )

            # For phase 1, return stub response
            # Phase 2+ will integrate with connector factory
            result = ToolCallResult(
                content=[
                    ToolContent(
                        type="text",
                        text=f"Tool execution for {request.params.name} not yet implemented. "
                             f"This is phase 1 of NexusMCP.",
                    )
                ],
                is_error=False,
            )

            add_span_attribute(span, "tool.result_type", "text")
            add_span_attribute(span, "http.status_code", 200)

            return ToolCallResponse(
                jsonrpc="2.0",
                method="tools/call",
                result=result,
                id=request.id,
            )

        except Exception as e:
            self.logger.error(f"Error handling tool call: {e}")
            if span:
                span.record_exception(e)
                span.set_attribute("error", True)
            return self.handler.create_error_response(
                request.id,
                ErrorCode.INTERNAL_ERROR,
                {"reason": str(e)},
            )
        finally:
            if span:
                span.end()


class ToolListHandler:
    """Handles tools/list method requests"""

    def __init__(self, handler: JSONRPCHandler):
        self.handler = handler
        self.logger = logging.getLogger(__name__)

    async def handle_tool_list(
        self,
        request: ToolListRequest,
        identity: Optional[Identity],
    ) -> Union[ToolListResponse, JSONRPCErrorResponse]:
        """Handle a tool list request"""
        span = create_span("handler.tool_list", {
            "request_id": request.id,
        })

        try:
            # Check identity
            if not identity:
                self.logger.warning("Missing identity for tool list")
                add_span_attribute(span, "tool.identity_missing", True)
                return self.handler.create_error_response(
                    request.id,
                    ErrorCode.TOKEN_VALIDATION_FAILED,
                )

            # For phase 1, return stub list
            # Phase 2+ will integrate with registry
            stub_tools = [
                ToolDefinition(
                    name="salesforce.query_opportunities",
                    description="Query Salesforce opportunities (Phase 2+)",
                    input_schema={"type": "object", "properties": {}},
                    required_scopes=["read_opportunities"],
                    rls_required=True,
                ),
                ToolDefinition(
                    name="salesforce.read_accounts",
                    description="Read Salesforce accounts (Phase 2+)",
                    input_schema={"type": "object", "properties": {}},
                    required_scopes=["read_accounts"],
                    rls_required=True,
                ),
            ]

            result = ToolListResult(
                tools=stub_tools,
                total=len(stub_tools),
                timestamp=datetime.utcnow(),
            )

            add_span_attribute(span, "tool.list_count", len(stub_tools))
            add_span_attribute(span, "http.status_code", 200)

            return ToolListResponse(
                jsonrpc="2.0",
                method="tools/list",
                result=result,
                id=request.id,
            )

        except Exception as e:
            self.logger.error(f"Error handling tool list: {e}")
            if span:
                span.record_exception(e)
                span.set_attribute("error", True)
            return self.handler.create_error_response(
                request.id,
                ErrorCode.INTERNAL_ERROR,
                {"reason": str(e)},
            )
        finally:
            if span:
                span.end()
