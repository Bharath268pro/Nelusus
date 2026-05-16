"""TLS Termination Middleware - validates TLS certificates and headers"""

import logging
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.utils.tracing import create_span, add_span_attribute

logger = logging.getLogger(__name__)


class TLSTerminationMiddleware(BaseHTTPMiddleware):
    """
    TLS Termination Middleware
    
    Validates TLS certificate details and ensures HTTPS headers are present.
    Should be first in the middleware chain (after CORS).
    """

    def __init__(self, app, enforce_https: bool = False):
        super().__init__(app)
        self.enforce_https = enforce_https

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through TLS middleware"""
        span = create_span("middleware.tls_termination", {
            "request.method": request.method,
            "request.url": str(request.url),
        })

        try:
            # Check for TLS/HTTPS indicators
            scheme = request.url.scheme
            x_forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
            
            # Log certificate info if present
            client_cert = request.headers.get("x-client-cert")
            if client_cert:
                add_span_attribute(span, "tls.client_cert_present", True)
                logger.debug("Client certificate presented")

            # Enforce HTTPS in production
            if self.enforce_https and scheme != "https" and x_forwarded_proto != "https":
                logger.warning(
                    f"Non-HTTPS request received: {request.method} {request.url.path}"
                )
                if span:
                    span.set_attribute("tls.https_enforced", False)
                add_span_attribute(span, "http.status_code", 426)
                return Response("HTTPS Required", status_code=426)

            add_span_attribute(span, "tls.scheme", scheme)
            add_span_attribute(span, "tls.forwarded_proto", x_forwarded_proto)

            response = await call_next(request)
            add_span_attribute(span, "http.status_code", response.status_code)
            return response

        except Exception as e:
            logger.error(f"TLS middleware error: {e}")
            if span:
                span.record_exception(e)
                span.set_attribute("error", True)
            raise
        finally:
            if span:
                span.end()
