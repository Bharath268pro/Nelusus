# Phase 12 — Observability

## 1. Architecture Explanation
When an agentic workflow spans an HTTP Gateway, a Redis FSM, an Async Celery worker, an LLM call to OpenAI, and an HTTP request to Salesforce, identifying *where* a 10-second latency bottleneck originated is impossible without **Distributed Tracing**.

An enterprise MCP platform achieves observability through three pillars:
1. **Traces (OpenTelemetry + Jaeger):** Every incoming request generates a unique `trace_id`. As the request moves through FastAPI, Celery, and external API clients, `span`s are attached to this trace. You can visualize the exact timeline of execution.
2. **Metrics (Prometheus + Grafana):** Counters and Histograms track aggregate health. E.g., "What is the P99 latency of our Salesforce connector?" or "How many workflows failed in the last 5 minutes?"
3. **Structured Logging (JSON):** Print statements are useless at scale. Logs must be emitted as JSON objects natively linking to the `trace_id` and `tenant_id` for querying in Datadog, Splunk, or ELK.

## 2. Folder Structure
```text
backend/app/
├── core/
│   ├── telemetry.py      # OpenTelemetry and Prometheus initialization
│   └── logging.py        # JSON structured logger configuration
└── main.py               # Hooks to inject telemetry into FastAPI
```

## 3. Exact Code Implementation

### A. OpenTelemetry Initialization (`core/telemetry.py`)
This bootstraps the OpenTelemetry SDK to export data to Jaeger (OTLP) and exposes Prometheus metrics.

```python
import os
from fastapi import FastAPI
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from prometheus_client import make_asgi_app

def setup_telemetry(app: FastAPI):
    # 1. Define the Service Resource (metadata attached to all traces)
    resource = Resource.create({
        "service.name": "nexusmcp-gateway",
        "service.version": "1.0.0",
        "environment": os.environ.get("ENVIRONMENT", "production")
    })

    # 2. Setup Tracing (Exports to Jaeger via OTLP)
    tracer_provider = TracerProvider(resource=resource)
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    
    # Batch processor is crucial for production to prevent blocking the event loop
    span_processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
    tracer_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(tracer_provider)

    # 3. Setup Prometheus Metrics Endpoint
    # Mounts /metrics for Prometheus to scrape
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    # 4. Auto-Instrument Libraries
    # This automatically creates spans for every incoming HTTP request to FastAPI
    FastAPIInstrumentor.instrument_app(app)
    # This automatically creates spans for every outgoing HTTP request (e.g. to OpenAI or Salesforce)
    HTTPXClientInstrumentor().instrument()

# Helper to get the global tracer
def get_tracer():
    return trace.get_tracer("nexusmcp.custom")
```

### B. Custom Spans inside the Orchestrator
We manually inject spans in critical areas (like Phase 10's orchestration engine) to track LLM latency specifically.

```python
# Inside app/orchestration/engine.py
from opentelemetry import trace
tracer = trace.get_tracer(__name__)

async def advance_workflow(session_id: str, user_context: UserContext):
    # Create a custom span for this FSM loop execution
    with tracer.start_as_current_span(
        "advance_workflow_loop", 
        attributes={
            "session.id": session_id,
            "tenant.id": user_context.tenant_id
        }
    ) as span:
        try:
            # ... execute logic ...
            if data["state"] == WorkflowState.PLANNING:
                with tracer.start_as_current_span("llm_reasoning"):
                    decision = await reason_next_step(...)
                    span.set_attribute("llm.decision_type", decision["type"])
                    
        except Exception as e:
            # Record exceptions explicitly in the trace
            span.record_exception(e)
            span.set_status(trace.status.Status(trace.status.StatusCode.ERROR))
            raise e
```

### C. Structured JSON Logging (`core/logging.py`)
Standardizes logs so they are easily queryable and automatically bound to the OpenTelemetry `trace_id`.

```python
import logging
import json
from opentelemetry import trace

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Automatically inject Trace ID if we are inside a span
        current_span = trace.get_current_span()
        if current_span.is_recording():
            log_obj["trace_id"] = format(current_span.get_span_context().trace_id, "032x")
            log_obj["span_id"] = format(current_span.get_span_context().span_id, "016x")

        # Inject extra kwargs passed to logger (e.g. logger.info("Hi", extra={"tenant": "123"}))
        if hasattr(record, "tenant_id"):
            log_obj["tenant_id"] = record.tenant_id

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    
    # Remove default handlers
    logger.handlers = []
    logger.addHandler(handler)
```

### D. Main Application Hook (`main.py`)
Tie it all together.

```python
from fastapi import FastAPI
from app.core.telemetry import setup_telemetry
from app.core.logging import setup_logging

setup_logging()
app = FastAPI(title="NexusMCP Gateway")

# Hook up OpenTelemetry and Prometheus
setup_telemetry(app)

@app.get("/health")
def health_check():
    return {"status": "ok"}
```

## 4. Security Reasoning
- **Data Scrubbing:** OpenTelemetry auto-instrumentation will grab URL parameters and headers. You MUST ensure that it does not log Authorization headers (JWTs) or sensitive parameters (SSNs in the URL). `HTTPXClientInstrumentor` usually strips Auth headers natively, but verify your OTLP exporter config.
- **Trace Injection:** Malicious users might send a `traceparent` header to spoof trace IDs. The gateway should be configured to trust incoming trace contexts ONLY from verified internal load balancers (e.g., NGINX/Envoy), generating new Trace IDs for external traffic.

## 5. Scaling Reasoning
- **BatchSpanProcessor:** Using `BatchSpanProcessor` instead of `SimpleSpanProcessor` is critical. It queues spans in memory and flushes them to Jaeger asynchronously over gRPC. If the Jaeger container goes down, your FastAPI app will NOT crash or slow down; it will simply drop traces.
- **Metrics Scraping:** Exposing `/metrics` for Prometheus to scrape (pull model) is highly scalable. Prometheus queries the endpoint every 15s. This places virtually zero load on FastAPI, unlike push-based metrics.

## 6. Common Production Pitfalls
- **High Cardinality Metrics:** Do NOT put raw `user_id`s or `session_id`s into Prometheus labels (e.g., `api_requests_total{user="123"}`). This creates "high cardinality" and will consume all RAM on your Prometheus server, eventually crashing it. Use labels only for bounded sets (e.g., `status_code="200"`, `tenant_id="acme"` if tenants < 1000).
- **Log Flooding:** Auto-instrumentation can be extremely verbose. You might find your logs flooded with `/health` checks or database ping commands. Use OpenTelemetry samplers (e.g., `TraceIdRatioBased`) to only sample 5% of traffic in massive production environments.

## 7. Enterprise Best Practices
- **Golden Signals:** In Grafana, build dashboards focused strictly on the Four Golden Signals for your MCP tools: **Latency** (Time to execute), **Traffic** (Requests per sec), **Errors** (Failure rates), and **Saturation** (Celery queue depth).
- **Audit Logs vs App Logs:** Trace and App logs are ephemeral (kept for ~14 days). Security Audit Logs (e.g., "User A executed `create_lead`") must be routed to a completely separate, immutable storage sink (like an S3 bucket with Object Lock) retained for 7 years for compliance.

## 8. Step-by-Step Setup Instructions
1. Install dependencies: `pip install opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-httpx opentelemetry-exporter-otlp prometheus-client`.
2. Add Jaeger and Prometheus to your `docker-compose.yml` (as we did previously in our codebase config).
3. Apply the `setup_telemetry(app)` inside `main.py`.
4. Run the app, execute a few tools, and navigate to `http://localhost:16686` (Jaeger UI) to visualize the exact waterfall of LLM reasoning latency vs External API latency.

---
**Status:** Phase 12 complete. All phases of the Enterprise MCP Integration walkthrough are now finished.
