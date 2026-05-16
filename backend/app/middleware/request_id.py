"""Request ID Middleware - generates and tracks unique request identifiers"""

import logging
import uuid
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.config import Settings
from app.utils.tracing import create_span, add_span_attribute

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Request ID Middleware
    
    Generates unique request IDs for request correlation and tracing.
    Injects ID into request state for access by downstream handlers.
    """

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings
        self.request_id_header = settings.request_id_header.lower()
        self.trace_id_header = settings.trace_id_header.lower()
        self.correlation_id_header = settings.correlation_id_header.lower()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through Request ID middleware"""
        # Extract or generate request ID
        request_id = request.headers.get(self.request_id_header) or str(uuid.uuid4())
        trace_id = request.headers.get(self.trace_id_header) or request_id
        correlation_id = request.headers.get(self.correlation_id_header) or request_id

        # Inject into request state
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        request.state.correlation_id = correlation_id

        span = create_span("middleware.request_id", {
            "request_id": request_id,
            "trace_id": trace_id,
            "correlation_id": correlation_id,
            "request.method": request.method,
            "request.path": request.url.path,
        })

        try:
            logger.debug(
                f"[{request_id}] {request.method} {request.url.path} - "
                f"Correlation: {correlation_id}"
            )

            response = await call_next(request)

            # Add request IDs to response headers
            response.headers[self.request_id_header] = request_id
            response.headers[self.trace_id_header] = trace_id
            response.headers[self.correlation_id_header] = correlation_id

            logger.debug(
                f"[{request_id}] Response: {response.status_code} - "
                f"{request.method} {request.url.path}"
            )

            add_span_attribute(span, "http.status_code", response.status_code)
            return response

        except Exception as e:
            logger.error(f"[{request_id}] Middleware error: {e}")
            if span:
                span.record_exception(e)
                span.set_attribute("error", True)
            raise
        finally:
            if span:
                span.end()
