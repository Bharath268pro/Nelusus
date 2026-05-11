"""API routes for the Security Proxy"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "mcp-security-proxy"}


@router.get("/version")
async def version():
    """Version endpoint"""
    return {"version": "0.1.0", "phase": "Phase 1 - Foundation"}
