"""Prompt Shield Middleware - detects and blocks prompt injection attacks"""

import logging
import re
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from app.config import Settings
from app.utils.tracing import create_span, add_span_attribute
from app.models.error_codes import create_jsonrpc_error, ErrorCode

logger = logging.getLogger(__name__)


class PromptShieldMiddleware(BaseHTTPMiddleware):
    """
    Prompt Shield Middleware
    
    Detects and blocks common prompt injection attack patterns.
    Uses heuristic detection (phase 1) with ML-based detection coming in phase 2+.
    """

    # Common prompt injection patterns to detect
    INJECTION_PATTERNS = [
        r"ignore previous.*instructions",
        r"forget the.*prompt",
        r"system prompt",
        r"administrator override",
        r"bypass.*security",
        r"execute.*code",
        r"run.*command",
        r"sql injection",
        r"<script",
        r"javascript:",
        r"on[a-z]+\s*=",
    ]

    # Compiled regex patterns for performance
    _compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in INJECTION_PATTERNS]

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through prompt shield middleware"""

        span = create_span("middleware.prompt_shield", {
            "request.method": request.method,
            "request.path": request.url.path,
        })

        try:
            # Only check POST/PUT requests with JSON body for injection patterns
            if request.method in {"POST", "PUT"}:
                try:
                    body = await request.body()
                    if body:
                        # Check for injection patterns in request body
                        body_str = body.decode("utf-8", errors="ignore").lower()
                        threat_detected = self._check_for_injection(body_str)

                        if threat_detected:
                            logger.warning(
                                f"[{getattr(request.state, 'request_id', '?')}] "
                                f"Prompt injection attack detected from {request.client.host}"
                            )
                            if span:
                                span.set_attribute("prompt_shield.attack_detected", True)
                                span.set_attribute("prompt_shield.threat", threat_detected)
                            
                            add_span_attribute(span, "http.status_code", 400)
                            error_response = create_jsonrpc_error(
                                ErrorCode.PROMPT_INJECTION_DETECTED,
                                data={
                                    "threat": threat_detected,
                                    "message": "Request contains potentially malicious content",
                                },
                            )
                            return JSONResponse(error_response.model_dump(), status_code=400)

                        add_span_attribute(span, "prompt_shield.clean", True)
                except Exception as e:
                    logger.error(
                        f"[{getattr(request.state, 'request_id', '?')}] "
                        f"Error reading request body: {e}"
                    )
                    if span:
                        span.record_exception(e)

                # Reconstruct request since we consumed the body
                async def receive():
                    return {"type": "http.request", "body": body}

                request._receive = receive

            response = await call_next(request)
            add_span_attribute(span, "http.status_code", response.status_code)
            return response

        except Exception as e:
            logger.error(
                f"[{getattr(request.state, 'request_id', '?')}] "
                f"Prompt shield middleware error: {e}"
            )
            if span:
                span.record_exception(e)
                span.set_attribute("error", True)
            add_span_attribute(span, "http.status_code", 500)
            error_response = create_jsonrpc_error(
                ErrorCode.INTERNAL_ERROR,
                data={"reason": "Security validation error"},
            )
            return JSONResponse(error_response.model_dump(), status_code=500)
        finally:
            if span:
                span.end()

    def _check_for_injection(self, text: str) -> Optional[str]:
        """Check text for injection patterns and return matching pattern if found"""
        for pattern in self._compiled_patterns:
            if pattern.search(text):
                return pattern.pattern
        return None
