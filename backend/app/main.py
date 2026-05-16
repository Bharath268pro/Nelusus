"""NexusMCP Gateway - Main FastAPI Application Factory

Phase 1: Foundation & Security Gateway
- TLS Termination
- Request ID & Correlation
- JWT RS256 Validation
- OAuth Scope Enforcement
- Row-Level Security (RLS) Context
- Prompt Injection Shield
- JSON-RPC 2.0 Engine
- Redis Caching
- OpenTelemetry Tracing
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZIPMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings, configure_logging
from app.routes import health_router, mcp_router
from app.middleware import (
    TLSTerminationMiddleware,
    RequestIDMiddleware,
    JWTValidationMiddleware,
    ScopeEnforcementMiddleware,
    RLSEnforcementMiddleware,
    PromptShieldMiddleware,
)
from app.utils.cache import initialize_cache, cleanup_cache, get_cache
from app.utils.tracing import setup_all_instrumentation, get_tracer

# Configure logging first
settings = get_settings()
logger = configure_logging(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown"""
    logger.info(
        f"Starting {settings.service_name} v{settings.service_version} (Phase 1 - Foundation)"
    )
    logger.info(f"Environment: {settings.environment}")

    # Initialize OpenTelemetry tracing
    tracer = None
    if settings.otel_enabled:
        try:
            setup_all_instrumentation(settings, app)
            tracer = get_tracer()
            logger.info("OpenTelemetry tracing initialized")
        except Exception as e:
            logger.error(f"Failed to initialize tracing: {e}")

    # Initialize Redis cache
    cache = None
    try:
        cache = await initialize_cache(settings)
        logger.info("Redis cache initialized")
    except Exception as e:
        logger.error(f"Failed to initialize cache: {e}")
        # Continue without cache - handled gracefully by cache client

    # Log middleware configuration
    logger.info("Middleware chain configured in order:")
    logger.info("  1. TLSTerminationMiddleware")
    logger.info("  2. RequestIDMiddleware")
    logger.info("  3. JWTValidationMiddleware")
    logger.info("  4. ScopeEnforcementMiddleware")
    logger.info("  5. RLSEnforcementMiddleware")
    logger.info("  6. PromptShieldMiddleware")

    yield

    # Cleanup
    logger.info(f"Shutting down {settings.service_name}...")
    try:
        await cleanup_cache()
        logger.info("Cache connection closed")
    except Exception as e:
        logger.error(f"Error closing cache: {e}")

    logger.info(f"{settings.service_name} shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application with all middleware"""

    app = FastAPI(
        title="NexusMCP Gateway",
        description="Production-grade MCP (Model Context Protocol) security gateway with JSON-RPC 2.0 support",
        version=settings.service_version,
        docs_url="/api/v1/docs" if settings.debug else None,
        redoc_url="/api/v1/redoc" if settings.debug else None,
        openapi_url="/api/v1/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    # ========== CORS Middleware ==========
    if settings.cors_enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=settings.cors_credentials,
            allow_methods=settings.cors_allow_methods,
            allow_headers=settings.cors_allow_headers,
            expose_headers=settings.cors_expose_headers,
        )
        logger.debug("CORS middleware enabled")

    # ========== GZIP Compression ==========
    app.add_middleware(GZIPMiddleware, minimum_size=1000)

    # ========== MIDDLEWARE CHAIN (in reverse order - LIFO processing) ==========
    # Middleware added last will be executed first

    # 6. Prompt Shield (last in chain - first to execute)
    app.add_middleware(PromptShieldMiddleware, settings=settings)

    # 5. RLS Enforcement
    app.add_middleware(RLSEnforcementMiddleware, settings=settings)

    # 4. Scope Enforcement
    app.add_middleware(ScopeEnforcementMiddleware, settings=settings)

    # 3. JWT Validation
    app.add_middleware(JWTValidationMiddleware, settings=settings)

    # 2. Request ID
    app.add_middleware(RequestIDMiddleware, settings=settings)

    # 1. TLS Termination (first in chain - last to execute)
    app.add_middleware(TLSTerminationMiddleware, enforce_https=settings.tls_enabled)

    logger.debug("All middleware registered in reverse order (LIFO)")

    # ========== ERROR HANDLERS ==========

    @app.exception_handler(Exception)
    async def generic_exception_handler(request, exc):
        """Handle uncaught exceptions"""
        logger.error(
            f"[{getattr(request.state, 'request_id', '?')}] "
            f"Unhandled exception: {exc}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": "Internal server error",
                },
                "id": getattr(request.state, "request_id", None),
            },
        )

    # ========== INCLUDE ROUTERS ==========
    app.include_router(health_router)
    app.include_router(mcp_router)

    # ========== STARTUP/SHUTDOWN EVENTS (alternative to lifespan) ==========

    @app.get("/api/v1/info")
    async def info():
        """Service information endpoint"""
        cache = get_cache()
        redis_stats = {}
        if cache:
            try:
                redis_stats = await cache.get_stats()
            except Exception:
                pass

        return {
            "service": settings.service_name,
            "version": settings.service_version,
            "phase": "Phase 1 - Foundation & Security Gateway",
            "environment": settings.environment,
            "redis": {
                "enabled": settings.redis_host is not None,
                "stats": redis_stats,
            },
            "tracing": {
                "enabled": settings.otel_enabled,
                "exporter": settings.otel_exporter_type,
            },
            "middleware": {
                "count": 6,
                "order": [
                    "TLSTerminationMiddleware",
                    "RequestIDMiddleware",
                    "JWTValidationMiddleware",
                    "ScopeEnforcementMiddleware",
                    "RLSEnforcementMiddleware",
                    "PromptShieldMiddleware",
                ],
            },
        }

    return app


# Create app instance
app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
