"""Phase 2D: Agent Orchestration REST Routes

POST /api/v1/agent/reason         – run full reasoning pipeline
GET  /api/v1/agent/sessions/{id}  – retrieve a reasoning session
POST /api/v1/agent/plan           – generate a plan (no execution)
POST /api/v1/agent/score          – score an entity match
POST /api/v1/agent/deduplicate    – run duplicate detection
GET  /api/v1/agent/connectors     – connector health status
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.agent_runtime import AgentReasoningRuntime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


# ─── DI ───────────────────────────────────────────────────────────────────────

def _get_runtime(request: Request) -> AgentReasoningRuntime:
    runtime = getattr(request.app.state, "agent_runtime", None)
    if not runtime:
        raise HTTPException(status_code=503, detail="Agent runtime not initialized")
    return runtime


# ─── Request Bodies ────────────────────────────────────────────────────────────

class ReasonRequest(BaseModel):
    intent: str = Field(..., description="Natural language intent")
    args: Dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = Field("default")
    user_id: str = Field("system")
    required_connectors: Optional[List[str]] = None
    existing_records: Optional[List[Dict[str, Any]]] = None


class PlanRequest(BaseModel):
    intent: str
    args: Dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = "default"
    user_id: str = "system"


class ScoreRequest(BaseModel):
    incoming: Dict[str, Any]
    candidate: Dict[str, Any]
    match_fields: List[str] = Field(default_factory=lambda: ["email", "name", "phone"])


class DedupRequest(BaseModel):
    incoming: Dict[str, Any]
    existing_records: List[Dict[str, Any]]
    tenant_id: str = "default"
    object_type: str = "Contact"
    namespace: str = "salesforce"


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post(
    "/reason",
    summary="Run Agent Reasoning Pipeline",
    description=(
        "Executes the full 6-stage agentic pipeline: "
        "context hydration → workflow planning → confidence scoring → "
        "duplicate detection → plan execution → rollback-on-failure. "
        "Returns the complete ReasoningSession including traces."
    ),
    status_code=200,
)
async def run_reasoning(
    body: ReasonRequest,
    request: Request,
    runtime: AgentReasoningRuntime = Depends(_get_runtime),
):
    try:
        session = await runtime.reason(
            intent=body.intent,
            input_args=body.args,
            tenant_id=body.tenant_id,
            user_id=body.user_id,
            required_connectors=body.required_connectors,
            existing_records=body.existing_records,
        )
        return session.model_dump(mode="json")
    except Exception as e:
        logger.error(f"[Route] reason error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/sessions/{session_id}",
    summary="Get Reasoning Session",
    description="Retrieve a past reasoning session by ID.",
)
async def get_session(
    session_id: str,
    request: Request,
    runtime: AgentReasoningRuntime = Depends(_get_runtime),
):
    session = await runtime.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.model_dump(mode="json")


@router.post(
    "/plan",
    summary="Generate Workflow Plan",
    description=(
        "Generate a multi-step WorkflowPlan without executing it. "
        "Useful for previewing what the agent will do."
    ),
)
async def generate_plan(
    body: PlanRequest,
    request: Request,
    runtime: AgentReasoningRuntime = Depends(_get_runtime),
):
    try:
        context = await runtime.hydration.hydrate(
            body.tenant_id, body.user_id, body.intent,
            required_connectors=runtime._infer_connectors(body.intent),
        )
        plan = runtime.planner.plan(body.intent, context, body.args)
        plan = runtime.rollback_planner.annotate(plan)
        return plan.model_dump(mode="json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/score",
    summary="Score Entity Match",
    description=(
        "Score the confidence of matching an incoming entity to a candidate record. "
        "Returns multi-dimensional ConfidenceScore."
    ),
)
async def score_match(
    body: ScoreRequest,
    request: Request,
    runtime: AgentReasoningRuntime = Depends(_get_runtime),
):
    try:
        score = runtime.scorer.score_entity_match(
            body.incoming, body.candidate, body.match_fields
        )
        return {
            "overall": score.overall,
            "tier": score.tier.value,
            "needs_approval": score.needs_approval,
            "dimensions": {
                "entity_match": score.entity_match,
                "schema_completeness": score.schema_completeness,
                "connector_reliability": score.connector_reliability,
                "policy_risk": score.policy_risk,
                "duplicate_likelihood": score.duplicate_likelihood,
                "historical_success": score.historical_success,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/deduplicate",
    summary="Detect Duplicates",
    description=(
        "Run duplicate detection on an incoming entity against a set of existing records. "
        "Performs email normalization, phone normalization, and fuzzy name matching."
    ),
)
async def detect_duplicates(
    body: DedupRequest,
    request: Request,
    runtime: AgentReasoningRuntime = Depends(_get_runtime),
):
    try:
        report = runtime.dedup.detect(
            body.incoming,
            body.existing_records,
            body.tenant_id,
            body.object_type,
            body.namespace,
        )
        return report.model_dump(mode="json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/connectors",
    summary="Connector Health Status",
    description="Returns the current health status of all registered connectors.",
)
async def connector_health(
    request: Request,
    runtime: AgentReasoningRuntime = Depends(_get_runtime),
):
    try:
        namespaces = ConnectorHealthRegistry.KNOWN_NAMESPACES
        result = {}
        for ns in namespaces:
            ctx = await runtime.hydration._health.get(ns)
            score = await runtime.hydration._health.reliability_score(ns)
            result[ns] = {
                "available": ctx.available,
                "latency_p99_ms": ctx.latency_p99_ms,
                "error_rate_pct": ctx.error_rate_pct,
                "auth_valid": ctx.auth_valid,
                "reliability_score": score,
            }
        return {"connectors": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Import needed for the route above
from app.services.agent_context import ConnectorHealthRegistry
