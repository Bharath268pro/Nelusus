"""JWT Validation Middleware - validates RS256 tokens and extracts identity"""

import logging
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from app.config import Settings
from app.models.jsonrpc import Identity
from app.services.jwt_auth import JWTValidator
from app.utils.cache import get_cache
from app.utils.tracing import create_span, add_span_attribute
from app.models.error_codes import create_jsonrpc_error, ErrorCode

logger = logging.getLogger(__name__)



class JWTValidationMiddleware(BaseHTTPMiddleware):
    """
    JWT Validation Middleware
    
    Validates RS256 JWT tokens from Authorization header.
    Extracts identity claims and injects into request state.
    Skips validation for health check endpoints.
    """

    # Endpoints that don't require authentication
    SKIP_AUTH_PATHS = {"/api/v1/health", "/health"}

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings
        self.validator = JWTValidator(get_cache(), settings)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through JWT validation middleware"""
        
        # Skip auth for certain paths
        if request.url.path in self.SKIP_AUTH_PATHS:
            return await call_next(request)

        span = create_span("middleware.jwt_validation", {
            "request.method": request.method,
            "request.path": request.url.path,
        })

        try:
            # Extract Authorization header
            auth_header = request.headers.get("Authorization")
            if not auth_header:
                logger.warning(
                    f"[{getattr(request.state, 'request_id', '?')}] "
                    f"Missing Authorization header"
                )
                if span:
                    span.set_attribute("jwt.missing", True)
                error_response = create_jsonrpc_error(
                    ErrorCode.TOKEN_VALIDATION_FAILED,
                    data={"reason": "Missing Authorization header"},
                )
                add_span_attribute(span, "http.status_code", 401)
                return JSONResponse(error_response.model_dump(), status_code=401)

            # Extract bearer token
            token = await self.validator.extract_bearer_token(auth_header)
            if not token:
                logger.warning(
                    f"[{getattr(request.state, 'request_id', '?')}] "
                    f"Invalid Authorization header format"
                )
                if span:
                    span.set_attribute("jwt.invalid_format", True)
                error_response = create_jsonrpc_error(
                    ErrorCode.TOKEN_VALIDATION_FAILED,
                    data={"reason": "Invalid Bearer token format"},
                )
                add_span_attribute(span, "http.status_code", 401)
                return JSONResponse(error_response.model_dump(), status_code=401)

            # Validate JWT and extract identity
            identity = await self.validator.validate_token(token)
            if not identity:
                logger.warning(
                    f"[{getattr(request.state, 'request_id', '?')}] "
                    f"JWT validation failed"
                )
                if span:
                    span.set_attribute("jwt.validation_failed", True)
                error_response = create_jsonrpc_error(
                    ErrorCode.TOKEN_VALIDATION_FAILED,
                    data={"reason": "Token validation failed"},
                )
                add_span_attribute(span, "http.status_code", 401)
                return JSONResponse(error_response.model_dump(), status_code=401)

            # Inject identity into request state
            request.state.identity = identity

            logger.debug(
                f"[{getattr(request.state, 'request_id', '?')}] "
                f"JWT validated for user: {identity.sub}"
            )

            # Add attributes to span
            add_span_attribute(span, "jwt.user_id", identity.sub)
            add_span_attribute(span, "jwt.tenant_id", identity.tenant_id)
            add_span_attribute(span, "jwt.scopes_count", len(identity.scopes))

            response = await call_next(request)
            add_span_attribute(span, "http.status_code", response.status_code)
            return response

        except Exception as e:
            logger.error(
                f"[{getattr(request.state, 'request_id', '?')}] "
                f"JWT middleware error: {e}"
            )
            if span:
                span.record_exception(e)
                span.set_attribute("error", True)
            add_span_attribute(span, "http.status_code", 500)
            error_response = create_jsonrpc_error(
                ErrorCode.INTERNAL_ERROR,
                data={"reason": "Authentication processing error"},
            )
            return JSONResponse(error_response.model_dump(), status_code=500)
        finally:
            if span:
                span.end()

    async def __del__(self):
        """Cleanup on middleware destruction"""
        await self.validator.close()
