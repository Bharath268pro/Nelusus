import logging
from typing import Any, Callable, Dict, List
from app.models.mcp_registry import ToolCallRequest, ToolCallResponse, ToolDefinition

logger = logging.getLogger(__name__)

import inspect

class ToolRegistryEngine:
    def __init__(self):
        # Maps tool_name -> (ToolDefinition, async_callable)
        self._tools: Dict[str, tuple[ToolDefinition, Callable]] = {}

    def register_tool(self, definition: ToolDefinition, handler: Callable):
        """Register a new tool into the MCP ecosystem."""
        if definition.name in self._tools:
            logger.warning(f"Overwriting existing tool: {definition.name}")
        self._tools[definition.name] = (definition, handler)
        logger.info(f"Registered tool: {definition.name}")

    def list_tools(self) -> List[ToolDefinition]:
        """Return all available tools for LLM discovery."""
        return [defn for defn, _ in self._tools.values()]

    async def execute_tool(self, request: ToolCallRequest, **kwargs) -> ToolCallResponse:
        """Route the execution request to the specific handler."""
        if request.tool_name not in self._tools:
            return ToolCallResponse(success=False, error=f"Tool '{request.tool_name}' not found")
        
        _, handler = self._tools[request.tool_name]
        
        try:
            # Safely check function signature to drop extra keyword arguments (like user_context)
            # if the target tool doesn't support them.
            sig = inspect.signature(handler)
            has_var_keyword = any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())
            
            executable_kwargs = {}
            if has_var_keyword:
                executable_kwargs = kwargs.copy()
            else:
                for k, v in kwargs.items():
                    if k in sig.parameters:
                        executable_kwargs[k] = v
                        
            # Phase 5: Salesforce Token Exchange & Client Injection
            sf_client = None
            if "sf_client" in sig.parameters and "user_context" in kwargs:
                user_context = kwargs["user_context"]
                # In production, we fetch the real tokens from the secure vault mapping to user_context.sub
                # Mock token retrieval for now
                from app.tools.salesforce.client import SalesforceClient
                sf_client = SalesforceClient(
                    instance_url="https://mock.salesforce.com",
                    access_token=f"mock_access_for_{user_context.sub}",
                    refresh_token="mock_refresh"
                )
                executable_kwargs["sf_client"] = sf_client
            
            try:
                # Execute the actual Python function asynchronously
                result = await handler(**request.arguments, **executable_kwargs)
                return ToolCallResponse(success=True, data=result)
            finally:
                if sf_client:
                    await sf_client.close()

        except TypeError as e:
            # Catch schema mismatch (e.g. LLM hallucinates an argument)
            logger.error(f"Schema violation in {request.tool_name}: {e}")
            return ToolCallResponse(success=False, error=f"Invalid arguments: {e}")
        except Exception as e:
            logger.error(f"Tool {request.tool_name} execution failed: {e}")
            return ToolCallResponse(success=False, error=str(e))

# Global singleton for FastAPI injection
registry = ToolRegistryEngine()
