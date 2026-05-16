"""Scope Enforcement Middleware - validates OAuth scopes for tool access"""

import logging
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from app.config import Settings
from app.models.jsonrpc import Identity
from app.services.jwt_auth import ScopeValidator
from app.utils.tracing import create_span, add_span_attribute
from app.models.error_codes import create_jsonrpc_error, ErrorCode

logger = logging.getLogger(__name__)


class ScopeEnforcementMiddleware(BaseHTTPMiddleware):
    """
    Scope Enforcement Middleware
    
    Validates that identity has required OAuth scopes for the requested tool/method.
    Scope requirements are checked against the tool registry (phase 2+).
    For phase 1, this middleware is prepared but scopes are logged only.
    """

    # Endpoints that don't require specific scopes (only authentication)
    SKIP_SCOPE_CHECK_PATHS = {"/api/v1/health", "/health", "/api/v1/tools/list"}

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through scope enforcement middleware"""

        # Skip scope check for certain paths
        if request.url.path in self.SKIP_SCOPE_CHECK_PATHS:
            return await call_next(request)

        span = create_span("middleware.scope_enforcement", {
            "request.method": request.method,
            "request.path": request.url.path,
        })

        try:
            # Check if identity exists (should be set by JWT middleware)
            identity: Optional[Identity] = getattr(request.state, "identity", None)
            if not identity:
                logger.warning(
                    f"[{getattr(request.state, 'request_id', '?')}] "
                    f"No identity found in request state"
                )
                if span:
                    span.set_attribute("scope.identity_missing", True)
                error_response = create_jsonrpc_error(
                    ErrorCode.INTERNAL_ERROR,
                    data={"reason": "Identity not authenticated"},
                )
                add_span_attribute(span, "http.status_code", 401)
                return JSONResponse(error_response.model_dump(), status_code=401)

            # Log identity scopes
            add_span_attribute(span, "scope.user_scopes", ",".join(identity.scopes))
            add_span_attribute(span, "scope.roles", ",".join(identity.roles))

            logger.debug(
                f"[{getattr(request.state, 'request_id', '?')}] "
                f"User scopes: {identity.scopes}"
            )

            # For phase 1, we log scopes but don't enforce specific requirements
            # Phase 2 will add tool registry integration
            logger.debug(
                f"[{getattr(request.state, 'request_id', '?')}] "
                f"Scope enforcement: Prepared (tool registry integration in phase 2)"
            )

            response = await call_next(request)
            add_span_attribute(span, "http.status_code", response.status_code)
            return response

        except Exception as e:
            logger.error(
                f"[{getattr(request.state, 'request_id', '?')}] "
                f"Scope enforcement middleware error: {e}"
            )
            if span:
                span.record_exception(e)
                span.set_attribute("error", True)
            add_span_attribute(span, "http.status_code", 500)
            error_response = create_jsonrpc_error(
                ErrorCode.INTERNAL_ERROR,
                data={"reason": "Scope validation error"},
            )
            return JSONResponse(error_response.model_dump(), status_code=500)
        finally:
            if span:
                span.end()
