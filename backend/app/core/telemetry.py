import os
from fastapi import FastAPI
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from prometheus_client import make_asgi_app

def setup_telemetry(app: FastAPI):
    resource = Resource.create({
        "service.name": "nexusmcp-gateway",
        "service.version": "1.0.0"
    })
    tracer_provider = TracerProvider(resource=resource)
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    
    # We ignore connection errors in dev if jaeger is missing
    span_processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True))
    tracer_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(tracer_provider)
    
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)
    
    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()

def get_tracer():
    return trace.get_tracer("nexusmcp.custom")
