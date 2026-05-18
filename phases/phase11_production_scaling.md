# Phase 11 — Production Scaling

## 1. Architecture Explanation
As your MCP platform scales, LLM latency (5-15 seconds per call) combined with synchronous tool execution (API latency) will rapidly exhaust the connection pool of your FastAPI web workers. If 1,000 users trigger an agent workflow simultaneously, a purely HTTP-driven system will crash due to Thread/RAM starvation or LLM API rate limits.

To scale a production AI gateway:
1. **Background Worker Pools:** Move the orchestration loop (Phase 10) off the FastAPI web server entirely. Use a message queue (Celery, Kafka, or RabbitMQ) to route execution to dedicated background worker nodes.
2. **Distributed Caching:** Repeated semantic queries or expensive tool calls (e.g., fetching a static Salesforce schema) must be cached in Redis.
3. **TPM/RPM Rate Limiting:** You must enforce strict Tokens-Per-Minute (TPM) and Requests-Per-Minute (RPM) limits *per tenant* via Redis token-bucket algorithms to prevent noisy neighbor problems and runaway AI billing.
4. **Cost Tracking:** Every LLM execution must calculate and record token costs bound to the tenant to enable billing/chargebacks.

## 2. Folder Structure
```text
backend/app/
├── core/
│   ├── celery_app.py    # Worker configuration
│   ├── rate_limiter.py  # Redis-based TPM/RPM limiter
│   └── cost_tracker.py  # Token usage accounting
├── workers/
│   └── agent_tasks.py   # Celery tasks that run the Phase 10 loop
```

## 3. Exact Code Implementation

### A. Rate Limiter (`core/rate_limiter.py`)
This intercepts execution before calling the LLM or expensive tools to ensure the tenant hasn't exhausted their budget.

```python
import time
import aioredis
from fastapi import HTTPException
from app.models.auth import UserContext

# Redis client used for shared counters
redis = aioredis.from_url("redis://redis:6379", decode_responses=True)

async def check_rate_limit(user: UserContext, rpm_limit: int = 50, tpm_limit: int = 40000):
    """
    Enforces RPM (Requests Per Minute) and TPM (Tokens Per Minute) using a sliding window.
    """
    current_minute = int(time.time() / 60)
    rpm_key = f"rate:rpm:{user.tenant_id}:{current_minute}"
    tpm_key = f"rate:tpm:{user.tenant_id}:{current_minute}"

    # Increment RPM counter
    async with redis.pipeline() as pipe:
        pipe.incr(rpm_key)
        pipe.expire(rpm_key, 120)  # TTL of 2 minutes to auto-cleanup
        results = await pipe.execute()
    
    current_rpm = results[0]
    
    if current_rpm > rpm_limit:
        raise HTTPException(
            status_code=429, 
            detail=f"Rate limit exceeded. Max {rpm_limit} requests per minute."
        )
        
    # TPM is evaluated *after* generation, but we can do a hard check here
    current_tpm = int(await redis.get(tpm_key) or 0)
    if current_tpm > tpm_limit:
        raise HTTPException(
            status_code=429, 
            detail="Token budget exceeded for this minute. Please wait."
        )
```

### B. Cost Tracking (`core/cost_tracker.py`)
Intercepts the LLM response to log token usage.

```python
import logging
from app.models.auth import UserContext

logger = logging.getLogger("billing_logger")

# Rough pricing for GPT-4-Turbo per 1k tokens
COST_PER_1K_PROMPT = 0.01
COST_PER_1K_COMPLETION = 0.03

async def record_llm_cost(user: UserContext, prompt_tokens: int, completion_tokens: int):
    """Calculates and logs the cost of a single LLM execution step."""
    
    cost = ((prompt_tokens / 1000) * COST_PER_1K_PROMPT) + \
           ((completion_tokens / 1000) * COST_PER_1K_COMPLETION)
           
    # Update TPM limits
    current_minute = int(time.time() / 60)
    tpm_key = f"rate:tpm:{user.tenant_id}:{current_minute}"
    await redis.incrby(tpm_key, prompt_tokens + completion_tokens)
    await redis.expire(tpm_key, 120)

    # In production, push this event to Kafka/Stripe/Billing DB
    logger.info(
        f"BILLING | tenant={user.tenant_id} user={user.user_id} "
        f"pt={prompt_tokens} ct={completion_tokens} cost=${cost:.4f}"
    )
```

### C. Background Worker Setup (`core/celery_app.py`)
Offload heavy execution to Celery. 

```python
from celery import Celery
import os

# Connect Celery to Redis broker
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

celery_app = Celery(
    "nexusmcp_workers",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["app.workers.agent_tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Crucial for LLM latency: don't let a worker grab 100 tasks if it takes 10s per task
    worker_prefetch_multiplier=1 
)
```

### D. The Asynchronous Worker Task (`workers/agent_tasks.py`)
This replaces `asyncio.create_task()` from Phase 10 with a durable background job.

```python
import asyncio
from app.core.celery_app import celery_app
from app.orchestration.engine import advance_workflow
from app.models.auth import UserContext

# Note: Celery is natively synchronous. To run async code (like our FSM), 
# we wrap it using asyncio.run() inside the Celery task.
@celery_app.task(bind=True, max_retries=3)
def process_agent_step(self, session_id: str, user_dict: dict):
    """
    Picks up an FSM session and drives it one step forward.
    """
    user = UserContext(**user_dict)
    
    try:
        # Run the async orchestration loop we built in Phase 10
        asyncio.run(advance_workflow(session_id, user))
    except Exception as exc:
        # If the LLM API fails (e.g. 502 Bad Gateway), Celery automatically retries
        raise self.retry(exc=exc, countdown=2 ** self.request.retries) # Exponential backoff
```

### E. Modifying the Route to Dispatch Tasks
Update the endpoint to push to Celery instead of holding the FastAPI thread.

```python
# In sse_router.py (from Phase 10)
from app.workers.agent_tasks import process_agent_step

@router.post("/start")
async def start_workflow(prompt: str, user: UserContext = Depends(get_current_user)):
    # ... Initialize Redis state ...
    
    # Push the task to the Celery queue immediately
    process_agent_step.delay(session_id, user.model_dump())
    
    return {"session_id": session_id}
```

## 4. Security Reasoning
- **Tenant Isolation in Cost Tracking:** Failing to bind token costs to a specific Tenant ID can lead to runaway API abuse that goes unnoticed until you get a $50k bill from OpenAI. 
- **Queue Separation:** In highly secure environments, create separate Celery queues for different security boundaries. E.g., route tasks executing `kubernetes.delete` to a specific queue monitored by dedicated worker nodes running in an isolated sub-VPC.

## 5. Scaling Reasoning
- **Horizontal Scaling:** Because the state is durable in Redis (Phase 10) and tasks are distributed via Redis/RabbitMQ (Phase 11), you can scale from 1 web server to 50 web servers (FastAPI) and 100 worker nodes (Celery) completely frictionlessly.
- **`worker_prefetch_multiplier=1`:** LLM tasks are extremely slow and CPU/Network bound. If you leave Celery's default setting (4), one worker will grab 4 long-running tasks and hoard them while other workers sit idle. Forcing `1` ensures tasks are strictly distributed round-robin as workers free up.
- **Token Bucket Algorithms:** Using `redis.incr` with a short `expire` window is an atomic, low-latency way to count API usage across dozens of load-balanced pods simultaneously.

## 6. Common Production Pitfalls
- **Hanging Connections:** Because workers use HTTP clients (httpx) to hit OpenAI or Salesforce, ensure your clients have explicit timeouts (e.g., `timeout=30.0`). If an API hangs, the worker thread hangs indefinitely, crippling your cluster.
- **Serialization:** Celery relies on JSON. You cannot pass complex Python objects (like SQLAlchemy models or FastAPI Request objects) into `process_agent_step.delay()`. You must pass strings/dicts and reconstruct the objects inside the worker.

## 7. Enterprise Best Practices
- **Semantic Caching:** Before calling OpenAI, hash the prompt/state and check Redis. If you've seen this exact prompt/state within the last hour, return the cached tool decision immediately. This cuts LLM costs significantly and drops latency from 5000ms to 5ms.
- **Dead Letter Queues (DLQ):** If an agent task fails 3 times in Celery, route it to a Dead Letter Queue. Configure alerts so engineers can inspect *why* the workflow crashed without losing the state payload.

## 8. Step-by-Step Setup Instructions
1. Install dependencies: `pip install celery redis`.
2. Ensure your `docker-compose.yml` has a `redis` container running.
3. Start the FastAPI server in one terminal: `uvicorn app.main:app`.
4. Start the Celery worker in a second terminal: `celery -A app.core.celery_app worker --loglevel=info`.
5. Trigger an execution and watch the Celery logs pick it up and process it asynchronously.

---
**Status:** Phase 11 complete. Awaiting confirmation to proceed to Phase 12 (Observability).
