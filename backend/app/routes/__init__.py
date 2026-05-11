"""Initialize routes module"""

from .health import router as health_router
from .mcp import router as mcp_router

__all__ = ["health_router", "mcp_router"]
