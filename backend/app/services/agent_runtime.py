"""Phase 2D: Agent Reasoning Runtime — Top-Level Orchestrator

AgentReasoningRuntime – drives the full reasoning pipeline:
  hydrate → plan → score → dedup → execute → rollback-on-failure

Also provides create_agent_runtime() factory.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from app.models.orchestration import (
    ConfidenceTier,
    DuplicateResolution,
    HydratedContext,
    PlanStep,
    PlanStepStatus,
    ReasoningSession,
    ReasoningTrace,
    WorkflowPlan,
)
from app.services.agent_context import (
    ConnectorHealthRegistry,
    ContextHydrationEngine,
)
from app.services.agent_scoring import (
    ConfidenceScoringEngine,
    DuplicateResolutionEngine,
)
from app.services.agent_planning import (
    CrossConnectorReasoner,
    RollbackAwareExecutionPlanner,
    ToolSelectionEngine,
    WorkflowPlanningEngine,
)

from app.services.real_connector_executor import RealConnectorExecutor

logger = logging.getLogger(__name__)

_SESSION_PREFIX = "nexusmcp:agent:session"


# ─── Connector Executor (stub + real delegation) ──────────────────────────────


class ConnectorExecutor:
    """
    Executes a single tool call against the appropriate connector.
    In Phase 2D this is a structured stub — production wires to connector_factory.
    """

    def __init__(self, health_registry: ConnectorHealthRegistry):
        self._health = health_registry

    async def execute(
        self,
        step: PlanStep,
        session: ReasoningSession,
    ) -> Dict[str, Any]:
        """Execute a step's tool call and return the result."""
        tool = step.tool
        args = step.args
        t0 = time.monotonic()

        # Internal tools are handled directly
        if tool.namespace == "internal":
            result = await self._execute_internal(tool.action, args, session)
            await self._health.record_call("internal", True, (time.monotonic() - t0) * 1000)
            return result

        # External connector stub (production: route to connector_factory)
        try:
            result = await self._execute_stub(tool.namespace, tool.action, args)
            latency = (time.monotonic() - t0) * 1000
            await self._health.record_call(tool.namespace, True, latency)
            return result
        except Exception as e:
            latency = (time.monotonic() - t0) * 1000
            await self._health.record_call(tool.namespace, False, latency)
            raise

    async def _execute_internal(
        self, action: str, args: Dict[str, Any], session: ReasoningSession
    ) -> Dict[str, Any]:
        """Handle internal tool actions."""
        if action == "check_duplicate":
            # Return dup_report from session if available
            if session.duplicate_report:
                return session.duplicate_report.model_dump(mode="json")
            return {"candidates": [], "resolution": "create_new", "confidence": 0.95}

        elif action == "score_confidence":
            if session.confidence:
                return {
                    "overall": session.confidence.overall,
                    "tier": session.confidence.tier.value,
                    "needs_approval": session.confidence.needs_approval,
                }
            return {"overall": 0.80, "tier": "medium", "needs_approval": False}

        elif action == "write_audit_log":
            return {
                "logged": True,
                "session_id": session.session_id,
                "timestamp": datetime.utcnow().isoformat(),
                "action": args.get("action", "unknown"),
                "entity_id": args.get("entity_id", "unknown"),
            }

        elif action == "extract_field":
            return {"extracted": True, "source": args.get("source_data", {})}

        return {"action": action, "args": args, "status": "executed"}

    async def _execute_stub(
        self, namespace: str, action: str, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Connector stub — returns realistic-looking mock data.
        Production: delegates to connector_factory.execute(namespace, action, args).
        """
        await asyncio.sleep(0.05)  # simulate network latency

        if namespace == "shopify" and action == "get_order":
            return {
                "id": args.get("order_id", "ORD-1234"),
                "status": "paid",
                "customer": {
                    "email": args.get("customer_email", "customer@example.com"),
                    "first_name": "Jane",
                    "last_name": "Smith",
                    "phone": "+1-555-0100",
                    "company": "Acme Corp",
                },
                "total_price": "149.99",
                "currency": "USD",
            }

        if namespace == "salesforce" and action in ("get_contact", "query_contacts"):
            return {
                "Id": "003CONTACT123",
                "Email": args.get("email", "customer@example.com"),
                "FirstName": "Jane",
                "LastName": "Smith",
                "Phone": "+15550100",
                "AccountId": "001ACCOUNT456",
            }

        if namespace == "salesforce" and action in ("create_contact", "upsert_contact"):
            return {
                "id": str(uuid.uuid4())[:18].upper(),
                "success": True,
                "created": True,
            }

        if namespace == "salesforce" and action in ("update_contact",):
            return {"id": args.get("contact_id", "003XYZ"), "success": True}

        return {
            "namespace": namespace,
            "action": action,
            "args": args,
            "status": "ok",
            "id": str(uuid.uuid4())[:18].upper(),
        }


# ─── Agent Reasoning Runtime ──────────────────────────────────────────────────


class AgentReasoningRuntime:
    """
    Top-level orchestrator for Phase 2D advanced agentic execution.

    Full pipeline:
    1. ContextHydrationEngine  → HydratedContext
    2. WorkflowPlanningEngine  → WorkflowPlan
    3. RollbackAwareExecutionPlanner → annotate plan
    4. ConfidenceScoringEngine → ConfidenceScore
    5. DuplicateResolutionEngine → DuplicateReport
    6. Plan execution with:
       - Step-by-step execution via ConnectorExecutor
       - Cross-connector reference injection
       - Confidence gate (escalate if LOW/CRITICAL)
       - Rollback on failure
    7. Session audit + memory store
    """

    def __init__(
        self,
        hydration: ContextHydrationEngine,
        planner: WorkflowPlanningEngine,
        rollback_planner: RollbackAwareExecutionPlanner,
        scorer: ConfidenceScoringEngine,
        dedup: DuplicateResolutionEngine,
        reasoner: CrossConnectorReasoner,
        executor: RealConnectorExecutor,
        cache=None,
    ):
        self.hydration = hydration
        self.planner = planner
        self.rollback_planner = rollback_planner
        self.scorer = scorer
        self.dedup = dedup
        self.reasoner = reasoner
        self.executor = executor
        self.cache = cache

    async def reason(
        self,
        intent: str,
        input_args: Dict[str, Any],
        tenant_id: str,
        user_id: str,
        required_connectors: Optional[List[str]] = None,
        existing_records: Optional[List[Dict[str, Any]]] = None,
        rls_context: Optional[Dict[str, Any]] = None,
        on_approval_required: Optional[Callable] = None,
    ) -> ReasoningSession:
        """
        Execute the full agent reasoning pipeline.

        Args:
            intent:              Natural language intent string
            input_args:          Seed args for the first step
            tenant_id:           Calling tenant
            user_id:             Calling user
            required_connectors: Connector namespaces to pre-hydrate
            existing_records:    Known records for duplicate detection
            rls_context:         RLS policies from middleware
            on_approval_required: Async callback when human approval is needed
        """
        session = ReasoningSession(
            tenant_id=tenant_id,
            user_id=user_id,
            intent=intent,
        )
        t0 = time.monotonic()

        try:
            # ── Step 1: Context Hydration ────────────────────────────────────
            connectors = required_connectors or self._infer_connectors(intent)
            t_ctx = time.monotonic()
            context = await self.hydration.hydrate(
                tenant_id, user_id, intent, connectors, rls_context
            )
            session.context = context
            session.add_trace(
                "context_hydration",
                f"connectors={connectors}",
                f"memory={len(context.memory_snippets)} snippets",
                latency_ms=(time.monotonic() - t_ctx) * 1000,
            )

            # ── Step 2: Workflow Planning ─────────────────────────────────────
            t_plan = time.monotonic()
            plan = self.planner.plan(intent, context, input_args)
            plan = self.rollback_planner.annotate(plan)
            session.plan = plan
            session.add_trace(
                "workflow_planning",
                f"intent={intent[:60]}",
                f"steps={plan.step_count}, template_confidence={plan.overall_confidence:.2%}",
                latency_ms=(time.monotonic() - t_plan) * 1000,
            )

            # ── Step 3: Confidence Scoring ────────────────────────────────────
            t_score = time.monotonic()
            connector_rel = {
                ns: await self.hydration._health.reliability_score(ns)
                for ns in plan.connectors_involved
            }
            confidence = self.scorer.score_plan(plan, context, connector_rel)
            session.confidence = confidence
            session.add_trace(
                "confidence_scoring",
                f"connectors={list(connector_rel.keys())}",
                f"overall={confidence.overall:.2%}, tier={confidence.tier.value}",
                confidence=confidence,
                latency_ms=(time.monotonic() - t_score) * 1000,
            )

            # ── Step 4: Duplicate Detection ───────────────────────────────────
            if existing_records is not None:
                t_dedup = time.monotonic()
                dup_report = self.dedup.detect(
                    input_args, existing_records, tenant_id
                )
                session.duplicate_report = dup_report
                session.add_trace(
                    "duplicate_detection",
                    f"candidates={len(dup_report.candidates)}",
                    f"resolution={dup_report.resolution.value}, "
                    f"confidence={dup_report.confidence:.2%}",
                    latency_ms=(time.monotonic() - t_dedup) * 1000,
                )
                # Re-score with duplicate likelihood
                confidence.duplicate_likelihood = (
                    1.0 - dup_report.confidence
                    if dup_report.resolution == DuplicateResolution.ESCALATE
                    else 0.95
                )
                session.confidence = confidence

            # ── Step 5: Confidence Gate ───────────────────────────────────────
            if confidence.tier == ConfidenceTier.CRITICAL:
                session.error = (
                    f"Confidence too low ({confidence.overall:.2%}) — "
                    "blocking execution. Human review required."
                )
                session.success = False
                session.total_latency_ms = (time.monotonic() - t0) * 1000
                return session

            if confidence.tier == ConfidenceTier.LOW and on_approval_required:
                await on_approval_required(session, "low_confidence")

            # ── Step 6: Execute Plan Steps ────────────────────────────────────
            await self._execute_plan(session, on_approval_required)

            session.success = all(
                s.status in (PlanStepStatus.COMPLETED, PlanStepStatus.SKIPPED)
                for s in session.plan.steps
            )

        except Exception as e:
            logger.error(f"[Reasoning] session {session.session_id} error: {e}")
            session.error = str(e)
            session.success = False

        finally:
            session.completed_at = datetime.utcnow()
            session.total_latency_ms = round((time.monotonic() - t0) * 1000, 2)

            # Store memory
            if session.success and session.plan:
                for step in session.plan.completed_steps:
                    if step.output_key and step.result:
                        await self.hydration.store_memory(
                            tenant_id,
                            f"last_{step.output_key}",
                            step.result,
                            ttl=3600,
                        )

            await self._persist_session(session)

        logger.info(
            f"[Reasoning] session={session.session_id} "
            f"success={session.success} "
            f"latency={session.total_latency_ms:.0f}ms"
        )
        return session

    async def _execute_plan(
        self,
        session: ReasoningSession,
        on_approval_required: Optional[Callable],
    ) -> None:
        """Execute plan steps respecting dependencies and parallel groups."""
        plan = session.plan
        completed_ids: set = set()

        for step in plan.steps:
            # Check dependencies
            if step.depends_on:
                missing = [d for d in step.depends_on if d not in completed_ids]
                if missing:
                    step.status = PlanStepStatus.SKIPPED
                    session.add_trace(
                        f"step_{step.step_index}_skipped",
                        f"missing deps: {missing}",
                    )
                    continue

            # Inject cross-connector references
            prior = [s for s in plan.steps if s.step_index < step.step_index]
            step = self.reasoner.inject_step_references(step, prior)

            # Approval gate for individual steps
            if step.requires_approval and on_approval_required:
                step.status = PlanStepStatus.AWAITING_APPROVAL
                await on_approval_required(session, f"step_{step.step_index}")
                # In a real system: wait for decision signal
                # For now: auto-approve in the stub runtime
                step.status = PlanStepStatus.PENDING

            # Execute
            step.started_at = datetime.utcnow()
            step.status = PlanStepStatus.RUNNING
            t_step = time.monotonic()

            try:
                result = await self.executor.execute(step, session)
                step.result = result
                step.status = PlanStepStatus.COMPLETED
                step.completed_at = datetime.utcnow()
                completed_ids.add(step.step_id)

                session.add_trace(
                    f"step_{step.step_index}_{step.tool.action}",
                    f"args={list(step.args.keys())}",
                    f"result_keys={list(result.keys()) if isinstance(result, dict) else 'ok'}",
                    latency_ms=(time.monotonic() - t_step) * 1000,
                )

            except Exception as e:
                step.status = PlanStepStatus.FAILED
                step.error = str(e)
                step.completed_at = datetime.utcnow()
                logger.error(
                    f"[Reasoning] Step {step.step_index} ({step.tool.full_name}) failed: {e}"
                )
                session.add_trace(
                    f"step_{step.step_index}_failed",
                    f"tool={step.tool.full_name}",
                    f"error={e}",
                    latency_ms=(time.monotonic() - t_step) * 1000,
                )

                # Trigger rollback
                rollback_msgs = await self.rollback_planner.execute_rollback(
                    plan, step,
                    lambda t, a: self.executor._execute_stub(t.namespace, t.action, a),
                )
                session.add_trace(
                    f"rollback_step_{step.step_index}",
                    output_summary="; ".join(rollback_msgs),
                )
                # Stop execution after failure + rollback
                break

    def _infer_connectors(self, intent: str) -> List[str]:
        """Infer which connectors are needed from the intent."""
        intent_lower = intent.lower()
        connectors = ["internal"]
        if "shopify" in intent_lower:
            connectors.append("shopify")
        if "salesforce" in intent_lower or "sfdc" in intent_lower or "crm" in intent_lower:
            connectors.append("salesforce")
        if "hubspot" in intent_lower:
            connectors.append("hubspot")
        if "zendesk" in intent_lower:
            connectors.append("zendesk")
        if "stripe" in intent_lower:
            connectors.append("stripe")
        if len(connectors) == 1:
            connectors.append("salesforce")  # default
        return connectors

    async def _persist_session(self, session: ReasoningSession) -> None:
        if not self.cache or not getattr(self.cache, "redis", None):
            return
        key = f"{_SESSION_PREFIX}:{session.session_id}"
        try:
            await self.cache.redis.setex(key, 3600, session.model_dump_json())
        except Exception as e:
            logger.error(f"[Reasoning] persist_session error: {e}")

    async def get_session(self, session_id: str) -> Optional[ReasoningSession]:
        """Retrieve a past reasoning session."""
        if not self.cache or not getattr(self.cache, "redis", None):
            return None
        key = f"{_SESSION_PREFIX}:{session_id}"
        try:
            raw = await self.cache.redis.get(key)
            if raw:
                return ReasoningSession.model_validate_json(raw)
        except Exception as e:
            logger.error(f"[Reasoning] get_session error: {e}")
        return None


# ─── Factory ──────────────────────────────────────────────────────────────────


def create_agent_runtime(cache=None) -> AgentReasoningRuntime:
    """Wire all Phase 2D components and return a ready AgentReasoningRuntime."""
    health = ConnectorHealthRegistry(cache)
    hydration = ContextHydrationEngine(health, cache)
    scorer = ConfidenceScoringEngine()
    dedup = DuplicateResolutionEngine()
    tool_selector = ToolSelectionEngine()
    cross_reasoner = CrossConnectorReasoner()
    planner = WorkflowPlanningEngine(tool_selector, cross_reasoner, scorer)
    rollback_planner = RollbackAwareExecutionPlanner()
    executor = RealConnectorExecutor(health)

    return AgentReasoningRuntime(
        hydration=hydration,
        planner=planner,
        rollback_planner=rollback_planner,
        scorer=scorer,
        dedup=dedup,
        reasoner=cross_reasoner,
        executor=executor,
        cache=cache,
    )
