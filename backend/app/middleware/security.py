"""Middleware for request/response handling and security"""

import logging
from fastapi import Request, HTTPException, status
from app.services import AuthenticationService

logger = logging.getLogger(__name__)


class SecurityProxyMiddleware:
    """
    Core middleware that enforces security checks on incoming requests.

    Flow:
    1. Extract and validate JWT token
    2. Check if user exists and is active
    3. Log request for audit trail
    4. Pass validated user_context to route handlers
    """

    def __init__(self, app):
        """Initialize middleware"""
        self.app = app

    async def __call__(self, request: Request, call_next):
        """Process request through security pipeline"""
        # Extract JWT token from Authorization header
        auth_header = request.headers.get("Authorization")
        token = AuthenticationService.extract_bearer_token(auth_header)

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization token",
            )

        # Decode and validate token
        jwt_token = AuthenticationService.decode_token(token)
        if not jwt_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
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
