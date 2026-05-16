"""RLS (Row-Level Security) Enforcement Middleware"""

import logging
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from app.config import Settings
from app.models.jsonrpc import Identity
from app.utils.cache import get_cache
from app.utils.tracing import create_span, add_span_attribute
from app.models.error_codes import create_jsonrpc_error, ErrorCode

logger = logging.getLogger(__name__)


class RLSEnforcementMiddleware(BaseHTTPMiddleware):
    """
    RLS (Row-Level Security) Enforcement Middleware
    
    Validates that user has access to requested resources based on RLS policies.
    RLS policies are stored in Redis cache and DynamoDB.
    For phase 1, this middleware is prepared but policies are logged only.
    """

    # Endpoints that don't require RLS checks
    SKIP_RLS_CHECK_PATHS = {"/api/v1/health", "/health"}

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings
        self.cache = get_cache()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through RLS enforcement middleware"""

        # Skip RLS check for certain paths
        if request.url.path in self.SKIP_RLS_CHECK_PATHS:
            return await call_next(request)

        span = create_span("middleware.rls_enforcement", {
            "request.method": request.method,
            "request.path": request.url.path,
        })

        try:
            # Check if identity exists
            identity: Optional[Identity] = getattr(request.state, "identity", None)
            if not identity:
                logger.warning(
                    f"[{getattr(request.state, 'request_id', '?')}] "
                    f"No identity found for RLS check"
                )
                if span:
                    span.set_attribute("rls.identity_missing", True)
                # Don't block - let upstream handlers decide
                return await call_next(request)

            # Store RLS context in request state for downstream handlers
            request.state.rls_context = {
                "tenant_id": identity.tenant_id,
                "user_id": identity.sub,
                "sf_user_id": identity.sf_user_id,
            }

            # Log RLS context
            add_span_attribute(span, "rls.tenant_id", identity.tenant_id)
            add_span_attribute(span, "rls.user_id", identity.sub)

            logger.debug(
                f"[{getattr(request.state, 'request_id', '?')}] "
                f"RLS context set - Tenant: {identity.tenant_id}"
            )

            # For phase 1, we prepare context but don't enforce policies
            # Phase 2+ will add policy evaluation
            logger.debug(
                f"[{getattr(request.state, 'request_id', '?')}] "
                f"RLS enforcement: Prepared (policy integration in phase 2+)"
            )

            response = await call_next(request)
            add_span_attribute(span, "http.status_code", response.status_code)
            return response

        except Exception as e:
            logger.error(
                f"[{getattr(request.state, 'request_id', '?')}] "
                f"RLS middleware error: {e}"
            )
            if span:
                span.record_exception(e)
                span.set_attribute("error", True)
            add_span_attribute(span, "http.status_code", 500)
            error_response = create_jsonrpc_error(
                ErrorCode.INTERNAL_ERROR,
                data={"reason": "RLS evaluation error"},
            )
            return JSONResponse(error_response.model_dump(), status_code=500)
        finally:
            if span:
                span.end()
