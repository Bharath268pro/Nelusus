"""Phase 2D: Advanced Agentic Orchestration — Core Data Models

All planning, reasoning, chaining, scoring, and duplicate resolution contracts.
Designed to stand alone on the existing NexusMCP base.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ─── Enumerations ─────────────────────────────────────────────────────────────


class ConnectorNamespace(str, Enum):
    SALESFORCE = "salesforce"
    SHOPIFY = "shopify"
    HUBSPOT = "hubspot"
    ZENDESK = "zendesk"
    STRIPE = "stripe"
    INTERNAL = "internal"


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"
    AWAITING_APPROVAL = "awaiting_approval"


class ReasoningStrategy(str, Enum):
    LINEAR = "linear"           # Sequential tool chain
    FANOUT = "fanout"           # Parallel across connectors
    CONDITIONAL = "conditional" # Branch on intermediate result
    LOOP = "loop"               # Iterate until condition
    FALLBACK = "fallback"       # Try alternatives on failure


class ConfidenceTier(str, Enum):
    HIGH = "high"       # >= 0.85 — auto-proceed
    MEDIUM = "medium"   # 0.60-0.84 — proceed with warning
    LOW = "low"         # 0.40-0.59 — require human approval
    CRITICAL = "critical"  # < 0.40 — block execution


class DuplicateResolution(str, Enum):
    CREATE_NEW = "create_new"
    UPDATE_EXISTING = "update_existing"
    MERGE = "merge"
    SKIP = "skip"
    ESCALATE = "escalate"


class RollbackStrategy(str, Enum):
    FULL = "full"         # Undo all completed steps
    PARTIAL = "partial"   # Undo from failure point backward
    NONE = "none"         # No rollback (idempotent ops)
    CHECKPOINT = "checkpoint"  # Roll back to last checkpoint


# ─── Tool Reference ───────────────────────────────────────────────────────────


class ToolRef(BaseModel):
    """A reference to a specific tool within a connector."""
    model_config = ConfigDict(extra="forbid")

    namespace: str = Field(..., description="Connector namespace: 'salesforce'")
    action: str = Field(..., description="Tool action: 'get_account'")
    version: str = Field("1.0.0")

    @property
    def full_name(self) -> str:
        return f"{self.namespace}.{self.action}"

    @classmethod
    def from_str(cls, name: str) -> "ToolRef":
        parts = name.split(".", 1)
        if len(parts) == 2:
            return cls(namespace=parts[0], action=parts[1])
        return cls(namespace="internal", action=name)


# ─── Plan Step ────────────────────────────────────────────────────────────────


class RollbackSpec(BaseModel):
    """Rollback specification for a single plan step."""
    model_config = ConfigDict(extra="forbid")

    tool: ToolRef
    args_template: Dict[str, Any] = Field(
        default_factory=dict,
        description="Args for the rollback call (supports {result.field} substitution)"
    )
    condition: str = Field(
        "always",
        description="When to trigger rollback: 'always' | 'on_failure' | 'on_cancel'"
    )
    timeout_seconds: int = 30


class PlanStep(BaseModel):
    """A single step in a multi-step agent workflow plan."""
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    step_index: int
    tool: ToolRef
    description: str = Field(..., description="Human-readable description of this step")
    args: Dict[str, Any] = Field(
        default_factory=dict,
        description="Args (may contain {prev.field} references to prior step results)"
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="step_ids this step depends on"
    )
    strategy: ReasoningStrategy = ReasoningStrategy.LINEAR
    parallel_group: Optional[str] = Field(
        None, description="Steps with same group_id run in parallel"
    )
    rollback: Optional[RollbackSpec] = None
    requires_approval: bool = False
    confidence_threshold: float = Field(
        0.60, ge=0.0, le=1.0,
        description="Min confidence to execute; below this → escalate"
    )
    timeout_seconds: int = 30
    retry_budget: int = Field(2, ge=0, le=5)
    output_key: Optional[str] = Field(
        None, description="Key to store result under for downstream reference"
    )

    # Execution state (mutable during run)
    status: PlanStepStatus = PlanStepStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retries_used: int = 0

    @property
    def latency_ms(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None


# ─── Workflow Plan ─────────────────────────────────────────────────────────────


class WorkflowPlan(BaseModel):
    """A complete multi-step plan produced by WorkflowPlanningEngine."""
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    intent: str = Field(..., description="Original agent intent")
    tenant_id: str
    user_id: str
    steps: List[PlanStep] = Field(default_factory=list)
    rollback_strategy: RollbackStrategy = RollbackStrategy.PARTIAL
    overall_confidence: float = Field(0.0, ge=0.0, le=1.0)
    connectors_involved: List[str] = Field(default_factory=list)
    estimated_duration_seconds: float = 0.0
    policy_flags: List[str] = Field(
        default_factory=list,
        description="Policy warnings: ['HIGH_RISK_MUTATION', 'CROSS_TENANT_READ']"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    planning_latency_ms: float = 0.0

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def completed_steps(self) -> List[PlanStep]:
        return [s for s in self.steps if s.status == PlanStepStatus.COMPLETED]

    @property
    def failed_steps(self) -> List[PlanStep]:
        return [s for s in self.steps if s.status == PlanStepStatus.FAILED]

    @property
    def pending_steps(self) -> List[PlanStep]:
        return [s for s in self.steps if s.status == PlanStepStatus.PENDING]

    def get_step(self, step_id: str) -> Optional[PlanStep]:
        return next((s for s in self.steps if s.step_id == step_id), None)


# ─── Context Models ────────────────────────────────────────────────────────────


class ConnectorContext(BaseModel):
    """Hydrated context for a single connector."""
    model_config = ConfigDict(extra="forbid")

    namespace: str
    available: bool = True
    latency_p99_ms: float = 0.0
    error_rate_pct: float = 0.0
    auth_valid: bool = True
    rate_limit_remaining: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    hydrated_at: datetime = Field(default_factory=datetime.utcnow)


class HydratedContext(BaseModel):
    """Full context hydrated for a reasoning session."""
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    user_id: str
    intent: str
    connector_contexts: Dict[str, ConnectorContext] = Field(default_factory=dict)
    historical_intents: List[str] = Field(
        default_factory=list,
        description="Recent similar intents from this tenant"
    )
    memory_snippets: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Relevant cached facts from previous executions"
    )
    rls_context: Dict[str, Any] = Field(default_factory=dict)
    hydration_latency_ms: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Confidence Models ─────────────────────────────────────────────────────────


class ConfidenceScore(BaseModel):
    """Multi-dimensional confidence score for a planning or matching decision."""
    model_config = ConfigDict(extra="forbid")

    entity_match: float = Field(0.0, ge=0.0, le=1.0, description="How well entities matched")
    schema_completeness: float = Field(0.0, ge=0.0, le=1.0, description="Required fields coverage")
    connector_reliability: float = Field(0.0, ge=0.0, le=1.0, description="Historical connector uptime")
    policy_risk: float = Field(0.0, ge=0.0, le=1.0, description="0=max risk, 1=no risk")
    duplicate_likelihood: float = Field(0.0, ge=0.0, le=1.0, description="Probability of duplicate")
    historical_success: float = Field(0.0, ge=0.0, le=1.0, description="Past success rate for this tool")

    @property
    def overall(self) -> float:
        """Weighted average of all dimensions."""
        weights = {
            "entity_match": 0.25,
            "schema_completeness": 0.20,
            "connector_reliability": 0.20,
            "policy_risk": 0.15,
            "duplicate_likelihood": 0.10,
            "historical_success": 0.10,
        }
        return round(sum(
            getattr(self, k) * w for k, w in weights.items()
        ), 4)

    @property
    def tier(self) -> ConfidenceTier:
        v = self.overall
        if v >= 0.85:
            return ConfidenceTier.HIGH
        elif v >= 0.60:
            return ConfidenceTier.MEDIUM
        elif v >= 0.40:
            return ConfidenceTier.LOW
        return ConfidenceTier.CRITICAL

    @property
    def needs_approval(self) -> bool:
        return self.tier in (ConfidenceTier.LOW, ConfidenceTier.CRITICAL)


# ─── Duplicate Detection Models ───────────────────────────────────────────────


class CandidateMatch(BaseModel):
    """A single duplicate candidate record."""
    model_config = ConfigDict(extra="forbid")

    record_id: str
    namespace: str
    object_type: str
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    match_reasons: List[str] = Field(default_factory=list)
    conflicting_fields: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DuplicateReport(BaseModel):
    """Result of duplicate detection for an incoming entity."""
    model_config = ConfigDict(extra="forbid")

    entity_fingerprint: str
    candidates: List[CandidateMatch] = Field(default_factory=list)
    resolution: DuplicateResolution
    confidence: float = Field(..., ge=0.0, le=1.0)
    recommended_record_id: Optional[str] = None
    reasoning: List[str] = Field(default_factory=list)
    detected_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def has_duplicates(self) -> bool:
        return bool(self.candidates)

    @property
    def best_match(self) -> Optional[CandidateMatch]:
        return max(self.candidates, key=lambda c: c.similarity_score) if self.candidates else None


# ─── Reasoning Session ────────────────────────────────────────────────────────


class ReasoningTrace(BaseModel):
    """A single reasoning step recorded by the AgentReasoningRuntime."""
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    step: str = Field(..., description="Reasoning step label")
    input_summary: str = ""
    output_summary: str = ""
    confidence: Optional[ConfidenceScore] = None
    latency_ms: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ReasoningSession(BaseModel):
    """Complete record of an agent reasoning session."""
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    user_id: str
    intent: str
    context: Optional[HydratedContext] = None
    plan: Optional[WorkflowPlan] = None
    confidence: Optional[ConfidenceScore] = None
    duplicate_report: Optional[DuplicateReport] = None
    traces: List[ReasoningTrace] = Field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    total_latency_ms: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    def add_trace(self, step: str, input_summary: str = "", output_summary: str = "",
                  confidence: Optional[ConfidenceScore] = None, latency_ms: float = 0.0) -> None:
        self.traces.append(ReasoningTrace(
            step=step, input_summary=input_summary,
            output_summary=output_summary, confidence=confidence,
            latency_ms=latency_ms,
        ))
