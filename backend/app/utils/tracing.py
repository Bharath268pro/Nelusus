"""OpenTelemetry tracing and instrumentation setup"""

import logging
from typing import Optional
from app.config import Settings

# OpenTelemetry imports
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

logger = logging.getLogger(__name__)

# Global tracer
_tracer: Optional[trace.Tracer] = None


def get_tracer() -> Optional[trace.Tracer]:
    """Get global tracer instance"""
    return _tracer


def initialize_tracing(settings: Settings) -> Optional[trace.Tracer]:
    """Initialize OpenTelemetry tracing with configured exporter"""
    global _tracer

    if not settings.otel_enabled:
        logger.info("OpenTelemetry tracing disabled")
        return None

    try:
        # Create resource
        resource = Resource(
            attributes={
                SERVICE_NAME: settings.otel_service_name,
                SERVICE_VERSION: settings.service_version,
                "environment": settings.otel_environment,
            }
        )

        # Create tracer provider
        tracer_provider = TracerProvider(resource=resource)

        # Configure exporter based on settings
        if settings.otel_exporter_type == "xray":
            logger.info("Using AWS X-Ray exporter")
            try:
                from opentelemetry.exporter.xray.trace_exporter import XRayExporter

                exporter = XRayExporter()
            except ImportError:
                logger.warning("X-Ray exporter not available, falling back to OTLP")
                exporter = OTLPSpanExporter(
                    endpoint=settings.otel_exporter_otlp_endpoint
                    or "http://localhost:4317"
                )
        elif settings.otel_exporter_type == "jaeger":
            logger.info("Using Jaeger exporter")
            exporter = JaegerExporter(
                agent_host_name="localhost",
                agent_port=6831,
            )
        else:
            logger.info("Using OTLP exporter")
            exporter = OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint
                or "http://localhost:4317"
            )

        # Add span processor
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

        # Set global tracer provider
        trace.set_tracer_provider(tracer_provider)

        # Get tracer instance
        _tracer = trace.get_tracer(__name__)

        logger.info(
            f"OpenTelemetry tracing initialized with {settings.otel_exporter_type} exporter"
        )
        return _tracer

    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry tracing: {e}")
        return None


def instrument_fastapi(app):
    """Instrument FastAPI application with OpenTelemetry"""
    try:
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumented with OpenTelemetry")
    except Exception as e:
        logger.error(f"Failed to instrument FastAPI: {e}")


def instrument_redis():
    """Instrument Redis client with OpenTelemetry"""
    try:
        RedisInstrumentor().instrument()
        logger.info("Redis instrumented with OpenTelemetry")
    except Exception as e:
        logger.error(f"Failed to instrument Redis: {e}")


def instrument_httpx():
    """Instrument HTTPX client with OpenTelemetry"""
    try:
        HTTPXClientInstrumentor().instrument()
        logger.info("HTTPX instrumented with OpenTelemetry")
    except Exception as e:
        logger.error(f"Failed to instrument HTTPX: {e}")


def instrument_requests():
    """Instrument requests library with OpenTelemetry"""
    try:
        RequestsInstrumentor().instrument()
        logger.info("Requests instrumented with OpenTelemetry")
    except Exception as e:
        logger.error(f"Failed to instrument requests: {e}")


def setup_all_instrumentation(settings: Settings, app=None) -> None:
    """Setup all OpenTelemetry instrumentation"""
    logger.info("Setting up OpenTelemetry instrumentation...")

    # Initialize tracing
    initialize_tracing(settings)

    # Instrument libraries
    instrument_redis()
    instrument_httpx()
    instrument_requests()

    # Instrument FastAPI if app provided
    if app:
        instrument_fastapi(app)

    logger.info("OpenTelemetry instrumentation setup complete")


def create_span(name: str, attributes: Optional[dict] = None) -> Optional[trace.Span]:
    """Create a new span for manual instrumentation"""
    if not _tracer:
        return None

    span = _tracer.start_span(name)
    if attributes:
        for key, value in attributes.items():
            span.set_attribute(key, value)

    return span


def add_span_attribute(span: Optional[trace.Span], key: str, value) -> None:
    """Add attribute to a span"""
    if span:
        span.set_attribute(key, value)


def record_span_event(
    span: Optional[trace.Span], name: str, attributes: Optional[dict] = None
) -> None:
    """Record an event in a span"""
    if span:
        span.add_event(name, attributes or {})
