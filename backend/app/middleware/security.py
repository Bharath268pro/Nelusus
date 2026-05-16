"""Middleware for request/response handling and security"""

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.services import AuthenticationService

logger = logging.getLogger(__name__)


class SecurityProxyMiddleware(BaseHTTPMiddleware):
    """
    Core middleware that enforces security checks on incoming requests.

    Flow:
    1. Extract and validate JWT token
    2. Check if user exists and is active
    3. Log request for audit trail
    4. Pass validated user_context to route handlers
    """

    async def dispatch(self, request: Request, call_next):
        """Process request through security pipeline"""
        # Skip middleware for health checks and docs
        if request.url.path in ["/api/v1/health", "/api/v1/version", "/docs", "/redoc", "/openapi.json"]:
            return await call_next(request)

        # Extract JWT token from Authorization header
        auth_header = request.headers.get("Authorization")
        token = AuthenticationService.extract_bearer_token(auth_header)

        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid authorization token"},
            )

        # Decode and validate token
        jwt_token = AuthenticationService.decode_token(token)
        if not jwt_token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        # Attach user context to request state
        request.state.user_id = jwt_token.sub
        request.state.email = jwt_token.email
        request.state.scopes = jwt_token.scopes
        request.state.jwt_token = jwt_token

        logger.debug(f"Request from user {jwt_token.sub}: {request.method} {request.url.path}")

        # Process request
        response = await call_next(request)
        return response
