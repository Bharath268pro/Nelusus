"""Tool registry and MCP tool definition models"""

from typing import Optional, Any, Dict, List
from datetime import datetime
from pydantic import BaseModel, Field
import re


class MCPToolDefinition(BaseModel):
    """Definition of an MCP tool for registry"""

    name: str = Field(
        ...,
        description="Tool name in format 'namespace.action' (e.g., 'salesforce.query_opportunities')",
    )
    description: str = Field(..., description="Human-readable tool description")
    version: str = Field("1.0.0", description="Tool version semver")
    input_schema: Dict[str, Any] = Field(
        ..., description="JSON Schema for tool input parameters"
    )
    output_schema: Optional[Dict[str, Any]] = Field(
        None, description="JSON Schema for tool output"
    )
    required_scopes: List[str] = Field(
        default_factory=list, description="OAuth scopes required to call this tool"
    )
    rls_required: bool = Field(
        False, description="Whether RLS (Row-Level Security) must be enforced"
    )
    connector_id: str = Field(
        ..., description="Which connector backend handles this tool"
    )
    tags: List[str] = Field(default_factory=list, description="Tool tags for discovery")
    examples: Optional[List[Dict[str, Any]]] = Field(
        None, description="Usage examples"
    )
    rate_limit_per_minute: Optional[int] = Field(
        None, description="Rate limit for this tool (per minute)"
    )
    timeout_seconds: int = Field(
        30, description="Tool call timeout in seconds"
    )
    cache_ttl_seconds: Optional[int] = Field(
        None, description="How long to cache results (None = no caching)"
    )
    deprecated: bool = Field(False, description="Whether this tool is deprecated")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def validate_namespace(self, pattern: str = r"^[a-z_]+\.[a-z_]+$") -> bool:
        """Validate tool name follows namespace.action pattern"""
        return bool(re.match(pattern, self.name))

    def get_namespace(self) -> str:
        """Extract namespace from tool name"""
        return self.name.split(".")[0]

    def get_action(self) -> str:
        """Extract action from tool name"""
        return self.name.split(".")[1] if "." in self.name else ""


class ToolRegistryEntry(BaseModel):
    """Entry in the tool registry"""

    id: str = Field(..., description="Unique tool ID (UUID)")
    tool: MCPToolDefinition = Field(..., description="Tool definition")
    active: bool = Field(True, description="Whether this tool is active")
    cached: bool = Field(False, description="Whether this entry is from cache")
    cache_timestamp: Optional[datetime] = Field(None, description="When cached")


class ToolsListResponse(BaseModel):
    """Response containing list of tools"""

    tools: List[MCPToolDefinition] = Field(..., description="List of tool definitions")
    total: int = Field(..., description="Total number of tools")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    from_cache: bool = Field(False, description="Whether result was cached")


class ToolRegistry(BaseModel):
    """In-memory tool registry representation"""

    tools: Dict[str, MCPToolDefinition] = Field(
        default_factory=dict, description="Mapping of tool name to definition"
    )
    last_refresh: Optional[datetime] = Field(
        None, description="When registry was last refreshed"
    )
    version: int = Field(0, description="Registry version counter")

    def register_tool(self, tool: MCPToolDefinition) -> None:
        """Register a tool in the registry"""
        if not tool.validate_namespace():
            raise ValueError(f"Invalid tool namespace: {tool.name}")
        self.tools[tool.name] = tool
        self.version += 1

    def get_tool(self, name: str) -> Optional[MCPToolDefinition]:
        """Get a tool by name"""
        return self.tools.get(name)

    def get_tools_by_namespace(self, namespace: str) -> List[MCPToolDefinition]:
        """Get all tools in a namespace"""
        return [t for t in self.tools.values() if t.get_namespace() == namespace]

    def get_tools_by_scope(self, scope: str) -> List[MCPToolDefinition]:
        """Get all tools requiring a specific scope"""
        return [
            t for t in self.tools.values() if scope in t.required_scopes
        ]

    def get_active_tools(self) -> List[MCPToolDefinition]:
        """Get all active (non-deprecated) tools"""
        return [t for t in self.tools.values() if not t.deprecated]

    def list_all(self) -> List[MCPToolDefinition]:
        """Get all tools"""
        return list(self.tools.values())


class ConnectorConfig(BaseModel):
    """Configuration for a tool connector (e.g., Salesforce, Shopify)"""

    id: str = Field(..., description="Connector ID (e.g., 'salesforce', 'shopify')")
    name: str = Field(..., description="Human-readable connector name")
    version: str = Field("1.0.0", description="Connector version")
    description: Optional[str] = Field(None, description="Connector description")
    endpoint_url: Optional[str] = Field(None, description="Connector endpoint URL")
    auth_type: str = Field(
        "oauth2", description="Authentication type: oauth2, apikey, etc"
    )
    enabled: bool = Field(True, description="Whether connector is enabled")
    priority: int = Field(
        0, description="Priority when multiple connectors can handle a tool"
    )
    health_check_url: Optional[str] = Field(None, description="Health check endpoint")
    health_check_interval_seconds: int = Field(
        300, description="How often to check connector health"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ConnectorFactory(BaseModel):
    """Factory for instantiating tool connectors"""

    connectors: Dict[str, ConnectorConfig] = Field(
        default_factory=dict, description="Registered connectors"
    )

    def register_connector(self, config: ConnectorConfig) -> None:
        """Register a connector"""
        self.connectors[config.id] = config

    def get_connector(self, connector_id: str) -> Optional[ConnectorConfig]:
        """Get connector by ID"""
        return self.connectors.get(connector_id)

    def get_connector_for_tool(self, tool_name: str) -> Optional[ConnectorConfig]:
        """Get connector for a specific tool (inferred from namespace)"""
        namespace = tool_name.split(".")[0] if "." in tool_name else None
        if namespace:
            return self.get_connector(namespace)
        return None

    def list_enabled_connectors(self) -> List[ConnectorConfig]:
        """Get all enabled connectors"""
        return [c for c in self.connectors.values() if c.enabled]
