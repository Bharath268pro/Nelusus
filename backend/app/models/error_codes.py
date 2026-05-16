"""Custom error codes and JSON-RPC 2.0 error handling"""

from enum import IntEnum
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field


class ErrorCode(IntEnum):
    """Custom error codes for NexusMCP gateway (extends JSON-RPC 2.0)"""

    # JSON-RPC 2.0 Standard Codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    SERVER_ERROR_START = -32099
    SERVER_ERROR_END = -32000

    # NexusMCP Custom Codes (reserved range: -32001 to -32099)
    SCOPE_VIOLATION = -32001
    RLS_DENIED = -32002
    TOOL_NOT_FOUND = -32003
    PROMPT_INJECTION_DETECTED = -32004
    ELICITATION_REQUIRED = -32005
    TOKEN_VALIDATION_FAILED = -32006
    TENANT_MISMATCH = -32007
    INVALID_TOOL_NAMESPACE = -32008
    RATE_LIMIT_EXCEEDED = -32009
    CONNECTOR_UNAVAILABLE = -32010
    CACHE_ERROR = -32011
    RLS_POLICY_EVAL_TIMEOUT = -32012


class ErrorCodeRegistry:
    """Registry of error codes with descriptions"""

    _registry: Dict[ErrorCode, Dict[str, str]] = {
        ErrorCode.PARSE_ERROR: {
            "message": "Parse error",
            "description": "Invalid JSON was received by the server.",
        },
        ErrorCode.INVALID_REQUEST: {
            "message": "Invalid Request",
            "description": "The JSON sent is not a valid Request object.",
        },
        ErrorCode.METHOD_NOT_FOUND: {
            "message": "Method not found",
            "description": "The method does not exist / is not available.",
        },
        ErrorCode.INVALID_PARAMS: {
            "message": "Invalid params",
            "description": "Invalid method parameter(s).",
        },
        ErrorCode.INTERNAL_ERROR: {
            "message": "Internal error",
            "description": "Internal JSON-RPC error.",
        },
        ErrorCode.SCOPE_VIOLATION: {
            "message": "Insufficient OAuth scope",
            "description": "JWT claims missing required scope for this tool.",
            "type": "ScopeViolation",
        },
        ErrorCode.RLS_DENIED: {
            "message": "Row-Level Security policy denied access",
            "description": "RLS evaluation determined access to this record is denied.",
            "type": "RLSViolation",
        },
        ErrorCode.TOOL_NOT_FOUND: {
            "message": "Tool not found",
            "description": "The requested tool is not registered in the tool registry.",
            "type": "ToolNotFound",
        },
        ErrorCode.PROMPT_INJECTION_DETECTED: {
            "message": "Prompt injection attack detected",
            "description": "Security shield detected potentially malicious input.",
            "type": "SecurityViolation",
        },
        ErrorCode.ELICITATION_REQUIRED: {
            "message": "Missing required parameter",
            "description": "One or more required parameters are missing from the tool call.",
            "type": "MissingParameter",
        },
        ErrorCode.TOKEN_VALIDATION_FAILED: {
            "message": "Token validation failed",
            "description": "JWT token could not be validated.",
            "type": "AuthenticationError",
        },
        ErrorCode.TENANT_MISMATCH: {
            "message": "Tenant mismatch",
            "description": "Token tenant does not match requested tenant.",
            "type": "AuthenticationError",
        },
        ErrorCode.INVALID_TOOL_NAMESPACE: {
            "message": "Invalid tool namespace",
            "description": "Tool namespace does not match required format.",
            "type": "ValidationError",
        },
        ErrorCode.RATE_LIMIT_EXCEEDED: {
            "message": "Rate limit exceeded",
            "description": "Too many requests in a given timeframe.",
            "type": "RateLimitError",
        },
        ErrorCode.CONNECTOR_UNAVAILABLE: {
            "message": "Connector unavailable",
            "description": "The requested connector is currently unavailable.",
            "type": "ConnectorError",
        },
        ErrorCode.CACHE_ERROR: {
            "message": "Cache error",
            "description": "An error occurred while accessing the cache layer.",
            "type": "CacheError",
        },
        ErrorCode.RLS_POLICY_EVAL_TIMEOUT: {
            "message": "RLS policy evaluation timeout",
            "description": "RLS policy evaluation exceeded timeout threshold.",
            "type": "RLSError",
        },
    }

    @classmethod
    def get(cls, code: ErrorCode) -> Dict[str, str]:
        """Get error info for a given code"""
        return cls._registry.get(code, {"message": "Unknown error"})

    @classmethod
    def message(cls, code: ErrorCode) -> str:
        """Get error message for a given code"""
        return cls.get(code).get("message", "Unknown error")


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 Error Object (RFC 7807 compliant)"""

    code: int = Field(..., description="JSON-RPC error code")
    message: str = Field(..., description="Human-readable error message")
    data: Optional[Dict[str, Any]] = Field(
        None, description="Additional error context and metadata"
    )


class JSONRPCErrorResponse(BaseModel):
    """JSON-RPC 2.0 Error Response"""

    jsonrpc: str = Field("2.0", description="JSON-RPC version")
    error: JSONRPCError = Field(..., description="Error object")
    id: Optional[str | int] = Field(None, description="Request ID")


class RFC7807Error(BaseModel):
    """RFC 7807 Problem Details for HTTP APIs"""

    type: str = Field(..., description="Error type URI")
    title: str = Field(..., description="Human-readable title")
    status: int = Field(..., description="HTTP status code")
    detail: Optional[str] = Field(None, description="Detailed explanation")
    instance: Optional[str] = Field(None, description="Problem instance URI")
    extensions: Optional[Dict[str, Any]] = Field(None, description="Custom extensions")


def create_jsonrpc_error(
    code: ErrorCode,
    request_id: Optional[str | int] = None,
    data: Optional[Dict[str, Any]] = None,
) -> JSONRPCErrorResponse:
    """Create a JSON-RPC error response"""
    error_info = ErrorCodeRegistry.get(code)
    error_data = data or {}

    # Merge in type if present
    if "type" in error_info:
        error_data["type"] = error_info["type"]

    return JSONRPCErrorResponse(
        error=JSONRPCError(
            code=code,
            message=error_info.get("message", "Unknown error"),
            data=error_data if error_data else None,
        ),
        id=request_id,
    )
