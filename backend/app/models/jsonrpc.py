"""Identity and JSON-RPC 2.0 protocol models"""

from typing import Optional, Any, Dict, List, Union
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


class Identity(BaseModel):
    """Authenticated user/service identity extracted from JWT claims"""

    sub: str = Field(..., description="Subject (user ID) from JWT")
    tenant_id: str = Field(..., description="Tenant identifier")
    sf_user_id: Optional[str] = Field(None, description="Salesforce user ID")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes")
    roles: List[str] = Field(default_factory=list, description="User roles")
    email: Optional[str] = Field(None, description="User email")
    iss: Optional[str] = Field(None, description="Issuer")
    aud: Optional[str] = Field(None, description="Audience")
    iat: Optional[int] = Field(None, description="Issued at (unix timestamp)")
    exp: Optional[int] = Field(None, description="Expiration (unix timestamp)")
    nbf: Optional[int] = Field(None, description="Not before (unix timestamp)")

    def has_scope(self, required_scope: str) -> bool:
        """Check if identity has a specific scope"""
        return required_scope in self.scopes

    def has_any_scope(self, scopes: List[str]) -> bool:
        """Check if identity has any of the given scopes"""
        return any(s in self.scopes for s in scopes)

    def has_all_scopes(self, scopes: List[str]) -> bool:
        """Check if identity has all of the given scopes"""
        return all(s in self.scopes for s in scopes)


# ============= JSON-RPC 2.0 Protocol Models =============


class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 Request Object"""

    jsonrpc: str = Field("2.0", description="JSON-RPC version")
    method: str = Field(..., description="Method name")
    params: Optional[Dict[str, Any] | List[Any]] = Field(
        None, description="Method parameters"
    )
    id: Optional[str | int] = Field(None, description="Request ID (null = notification)")


class JSONRPCResult(BaseModel):
    """JSON-RPC 2.0 Success Response"""

    jsonrpc: str = Field("2.0", description="JSON-RPC version")
    result: Any = Field(..., description="Result of the method call")
    id: Optional[str | int] = Field(..., description="Request ID")


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 Error Object"""

    code: int = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    data: Optional[Any] = Field(None, description="Additional error data")


class JSONRPCErrorResponse(BaseModel):
    """JSON-RPC 2.0 Error Response"""

    jsonrpc: str = Field("2.0", description="JSON-RPC version")
    error: JSONRPCError = Field(..., description="Error object")
    id: Optional[str | int] = Field(None, description="Request ID")


# ============= Tool Call Models =============


class ToolCallParams(BaseModel):
    """Parameters for tools/call method"""

    name: str = Field(..., description="Tool name in format 'namespace.action'")
    arguments: Dict[str, Any] = Field(
        default_factory=dict, description="Tool-specific arguments"
    )


class ToolCallRequest(JSONRPCRequest):
    """Request to call a tool"""

    method: str = Field("tools/call", description="Method name")
    params: ToolCallParams = Field(..., description="Tool call parameters")


class ToolContent(BaseModel):
    """Content item in tool response"""

    type: str = Field(..., description="Content type: 'text', 'image', 'json', etc")
    text: Optional[str] = Field(None, description="Text content")
    data: Optional[Dict[str, Any] | Any] = Field(None, description="Structured data")
    mime_type: Optional[str] = Field(None, description="MIME type for binary content")


class ToolCallResult(BaseModel):
    """Result of a tool call"""

    content: List[ToolContent] = Field(
        default_factory=list, description="Result content items"
    )
    is_error: bool = Field(False, description="Whether this is an error result")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ToolCallResponse(JSONRPCResult):
    """Response from tools/call method"""

    method: str = Field("tools/call", description="Method name")
    result: ToolCallResult = Field(..., description="Tool call result")


# ============= Tool List Models =============


class ToolListRequest(JSONRPCRequest):
    """Request to list available tools"""

    method: str = Field("tools/list", description="Method name")


class ToolDefinition(BaseModel):
    """Definition of a tool"""

    name: str = Field(..., description="Tool name in format 'namespace.action'")
    description: str = Field(..., description="Tool description")
    input_schema: Dict[str, Any] = Field(
        ..., description="JSON Schema for tool input parameters"
    )
    output_schema: Optional[Dict[str, Any]] = Field(
        None, description="JSON Schema for tool output"
    )
    required_scopes: List[str] = Field(
        default_factory=list, description="Required OAuth scopes"
    )
    rls_required: bool = Field(
        False, description="Whether RLS evaluation is required"
    )


class ToolListResult(BaseModel):
    """Result of tools/list method"""

    tools: List[ToolDefinition] = Field(..., description="List of available tools")
    total: int = Field(..., description="Total number of available tools")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ToolListResponse(JSONRPCResult):
    """Response from tools/list method"""

    method: str = Field("tools/list", description="Method name")
    result: ToolListResult = Field(..., description="Tool list result")


# ============= Batch Request Models =============


class BatchRequest(BaseModel):
    """Batch of JSON-RPC requests"""

    requests: List[JSONRPCRequest] = Field(..., description="Array of requests")

    def __len__(self) -> int:
        return len(self.requests)

    def is_valid_batch(self) -> bool:
        """Validate batch constraints"""
        # Empty array is invalid per JSON-RPC spec
        if len(self.requests) == 0:
            return False
        # All requests must be valid
        return all(r.jsonrpc == "2.0" for r in self.requests)


class BatchResponse(BaseModel):
    """Batch response containing multiple results"""

    responses: List[Union[JSONRPCResult, JSONRPCErrorResponse]] = Field(
        ..., description="Array of responses"
    )


# ============= SSE Models =============


class SSEMessage(BaseModel):
    """Server-Sent Event message"""

    id: Optional[str] = Field(None, description="Event ID")
    event: str = Field(..., description="Event type")
    data: Dict[str, Any] = Field(..., description="Event data")
    retry: Optional[int] = Field(None, description="Retry timeout in ms")

    def to_sse_format(self) -> str:
        """Convert to SSE wire format"""
        import json

        lines = []
        if self.id:
            lines.append(f"id: {self.id}")
        lines.append(f"event: {self.event}")
        lines.append(f"data: {json.dumps(self.data)}")
        if self.retry:
            lines.append(f"retry: {self.retry}")
        lines.append("")  # Empty line to mark end of message
        return "\n".join(lines)


# ============= Health Check Models =============


class HealthStatus(str, Enum):
    """Health status enumeration"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthCheckResponse(BaseModel):
    """API health check response"""

    status: HealthStatus = Field(..., description="Overall health status")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str = Field(..., description="Service version")
    dependencies: Dict[str, HealthStatus] = Field(
        default_factory=dict, description="Dependency health status"
    )
    uptime_seconds: float = Field(..., description="Service uptime in seconds")
