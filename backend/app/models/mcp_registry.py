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
    data: Optional[Any] = None
    error: Optional[str] = None
