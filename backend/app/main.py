"""Main FastAPI application factory"""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import settings
from app.routes import health_router, mcp_router
from app.middleware import SecurityProxyMiddleware

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown"""
    logger.info("Starting MCP Security Proxy...")
    yield
    logger.info("Shutting down MCP Security Proxy...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""

    app = FastAPI(
        title="MCP Security Proxy",
        description="Security middleware for Model Context Protocol agents accessing Salesforce",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:8080"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security middleware
    app.add_middleware(SecurityProxyMiddleware)

    # Include routers
    app.include_router(health_router)
    app.include_router(mcp_router)

    return app


# Create app instance
app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
