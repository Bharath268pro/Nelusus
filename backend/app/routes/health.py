"""Health check endpoint"""

import logging
from datetime import datetime
from fastapi import APIRouter, Depends, Request
from app.config import Settings, get_settings
from app.models.jsonrpc import HealthCheckResponse, HealthStatus
from app.utils.cache import get_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["health"])

# Track startup time for uptime calculation
_startup_time = datetime.utcnow()


@router.get("/health", response_model=HealthCheckResponse)
async def health_check(settings: Settings = Depends(get_settings)):
    """Health check endpoint"""
    try:
        cache = get_cache()
        redis_healthy = False
        if cache:
            redis_healthy = await cache.health_check()

        uptime = (datetime.utcnow() - _startup_time).total_seconds()

        dependencies = {
            "redis": HealthStatus.HEALTHY if redis_healthy else HealthStatus.UNHEALTHY,
        }

        overall_status = (
            HealthStatus.HEALTHY
            if all(s == HealthStatus.HEALTHY for s in dependencies.values())
            else HealthStatus.DEGRADED
        )

        return HealthCheckResponse(
            status=overall_status,
            version=settings.service_version,
            dependencies=dependencies,
            uptime_seconds=uptime,
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthCheckResponse(
            status=HealthStatus.UNHEALTHY,
            version=settings.service_version,
            dependencies={"error": str(e)},
            uptime_seconds=0,
        )


@router.get("/version")
async def version(settings: Settings = Depends(get_settings)):
    """Version endpoint"""
    return {
        "version": settings.service_version,
        "service": settings.service_name,
        "phase": "Phase 1 - Foundation & Security Gateway",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/ready")
async def readiness_check(settings: Settings = Depends(get_settings)):
    """Readiness check endpoint (for Kubernetes)"""
    try:
        cache = get_cache()
        if cache:
            is_ready = await cache.health_check()
            if is_ready:
                return {"ready": True, "timestamp": datetime.utcnow().isoformat()}

        return {
            "ready": False,
            "reason": "Cache not available",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return {
            "ready": False,
            "reason": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }
