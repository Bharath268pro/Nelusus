"""MCP (Model Context Protocol) schema models for the Security Proxy"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from enum import Enum


class ToolArgument(BaseModel):
    """Represents a single argument to a tool"""

    name: str = Field(..., description="Argument name")
    type: str = Field(..., description="Argument type (string, number, boolean, etc.)")
    required: bool = Field(default=True, description="Whether this argument is required")
    description: Optional[str] = Field(None, description="Human-readable description")
    value: Any = Field(None, description="The actual value of the argument")


class MCPToolCall(BaseModel):
    """Represents an MCP tool call request from the agent"""

    tool_name: str = Field(..., description="Name of the tool to call")
    tool_version: str = Field(default="1.0", description="Version of the tool")
    arguments: Dict[str, Any] = Field(..., description="Tool arguments")
    request_id: str = Field(..., description="Unique request ID for tracking")
    timestamp: str = Field(..., description="ISO 8601 timestamp")


class MCPRequest(BaseModel):
    """MCP request from the agent to the Security Proxy"""

    user_id: str = Field(..., description="User ID from JWT")
    auth_token: str = Field(..., description="Bearer JWT token")
    tool_call: MCPToolCall = Field(..., description="The tool call to execute")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")


class MCPResponse(BaseModel):
    """MCP response from the Security Proxy to the agent"""

    request_id: str = Field(..., description="Matching request ID")
    status: str = Field(..., description="Response status (success, error)")
    data: Optional[Dict[str, Any]] = Field(None, description="Response data")
    error: Optional[str] = Field(None, description="Error message if status is error")
    redaction_applied: bool = Field(default=False, description="Whether PII redaction was applied")
    cache_hit: bool = Field(default=False, description="Whether response came from cache")
    execution_time_ms: float = Field(..., description="Execution time in milliseconds")


class ToolStatus(str, Enum):
    """Status of a tool operation"""

    AVAILABLE = "available"
    RESTRICTED = "restricted"
    DENIED = "denied"
    ERROR = "error"
