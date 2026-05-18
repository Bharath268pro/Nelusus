"""Phase 2D: Workflow Planning Engine + Rollback-Aware Execution Planner

WorkflowPlanningEngine       – generates multi-step plans from intent + context
RollbackAwareExecutionPlanner – annotates plans with rollback specs, tracks checkpoints
ToolSelectionEngine           – selects best tool for each step
CrossConnectorReasoner        – resolves cross-connector data flows
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.models.orchestration import (
    ConfidenceScore,
    ConfidenceTier,
    ConnectorContext,
    DuplicateReport,
    DuplicateResolution,
    HydratedContext,
    PlanStep,
    PlanStepStatus,
    ReasoningStrategy,
    RollbackSpec,
    RollbackStrategy,
    ToolRef,
    WorkflowPlan,
)
from app.services.agent_scoring import ConfidenceScoringEngine

logger = logging.getLogger(__name__)


# ─── Tool Selection Engine ────────────────────────────────────────────────────


class ToolSelectionEngine:
    """
    Selects the most appropriate tool for each step of the plan.

    Selection logic:
    1. Parse intent keywords → action verbs + entity types
    2. Map to connector namespace + action
    3. Apply connector availability filter
    4. Rank by confidence score
    """

    # Intent keyword → (namespace, action) mapping
    INTENT_MAP: Dict[str, Tuple[str, str]] = {
        # Shopify
        "shopify order": ("shopify", "get_order"),
        "shopify customer": ("shopify", "get_customer"),
        "shopify product": ("shopify", "get_product"),
        # Salesforce
        "salesforce account": ("salesforce", "get_account"),
        "salesforce contact": ("salesforce", "get_contact"),
        "salesforce lead": ("salesforce", "get_lead"),
        "salesforce opportunity": ("salesforce", "get_opportunity"),
        "create contact": ("salesforce", "create_contact"),
        "update contact": ("salesforce", "update_contact"),
        "create account": ("salesforce", "create_account"),
        "update account": ("salesforce", "update_account"),
        "create lead": ("salesforce", "create_lead"),
        # Generic
        "customer lookup": ("salesforce", "get_contact"),
        "duplicate check": ("internal", "check_duplicate"),
        "audit": ("internal", "write_audit_log"),
    }

    def select(
        self,
        step_description: str,
        context: HydratedContext,
        preferred_namespace: Optional[str] = None,
    ) -> ToolRef:
        """Select the best ToolRef for a step description."""
        desc_lower = step_description.lower()

        # Try direct keyword match
        for keyword, (ns, action) in self.INTENT_MAP.items():
            if keyword in desc_lower:
                # Check connector availability
                ctx = context.connector_contexts.get(ns)
                if ctx and not ctx.available:
                    logger.warning(f"[ToolSelection] {ns} unavailable, using fallback")
                    continue
                return ToolRef(namespace=ns, action=action)

        # Fallback: use preferred_namespace or internal
        ns = preferred_namespace or "internal"
        return ToolRef(namespace=ns, action="generic_execute")

    def get_required_fields(self, tool: ToolRef) -> List[str]:
        """Return required field names for a tool (stub — production: from schema cache)."""
        REQUIRED: Dict[str, List[str]] = {
            "shopify.get_order": ["order_id"],
            "shopify.get_customer": ["customer_id"],
            "salesforce.get_account": ["account_id"],
            "salesforce.get_contact": ["contact_id"],
            "salesforce.create_contact": ["email", "last_name", "account_id"],
            "salesforce.update_contact": ["contact_id"],
            "salesforce.create_account": ["name"],
            "salesforce.update_account": ["account_id", "name"],
            "salesforce.create_lead": ["email", "last_name", "company"],
            "internal.check_duplicate": ["email"],
            "internal.write_audit_log": ["action", "entity_id"],
        }
        return REQUIRED.get(tool.full_name, [])


# ─── Cross-Connector Reasoner ─────────────────────────────────────────────────


class CrossConnectorReasoner:
    """
    Resolves data flow between connectors:
    - Identifies which fields from Step A feed Step B
    - Detects schema mismatches between connectors
    - Plans field mapping / transformation

    Example:
    shopify.get_order → result.customer.email
    → becomes input to → salesforce.get_contact(email={prev.customer.email})
    """

    # Cross-connector field mappings
    FIELD_MAPPINGS: Dict[str, Dict[str, str]] = {
        "shopify→salesforce": {
            "customer.email": "email",
            "customer.first_name": "first_name",
            "customer.last_name": "last_name",
            "customer.phone": "phone",
            "customer.company": "account_name",
            "billing_address.city": "mailing_city",
            "billing_address.country": "mailing_country",
        },
        "salesforce→hubspot": {
            "Email": "email",
            "FirstName": "firstname",
            "LastName": "lastname",
            "Phone": "phone",
            "AccountId": "company",
        },
    }

    def resolve_data_flow(
        self,
        source_ns: str,
        target_ns: str,
        source_fields: List[str],
    ) -> Dict[str, str]:
        """
        Return field mapping: {source_field → target_field}.
        """
        mapping_key = f"{source_ns}→{target_ns}"
        mapping = self.FIELD_MAPPINGS.get(mapping_key, {})
        return {f: mapping.get(f, f) for f in source_fields if f in mapping}

    def inject_step_references(
        self,
        step: PlanStep,
        prior_steps: List[PlanStep],
    ) -> PlanStep:
        """
        Replace {step_N.field} template references in step.args with
        actual result references for execution.
        """
        updated_args = dict(step.args)
        for key, value in updated_args.items():
            if isinstance(value, str) and value.startswith("{") and "." in value:
                # e.g. "{shopify_order.customer.email}"
                ref = value.strip("{}")
                parts = ref.split(".", 1)
                ref_key = parts[0]
                field_path = parts[1] if len(parts) > 1 else ""
                # Find the prior step that produced this output_key
                source = next(
                    (s for s in prior_steps if s.output_key == ref_key), None
                )
                if source and source.result:
                    resolved = self._extract_path(source.result, field_path)
                    if resolved is not None:
                        updated_args[key] = resolved
        step.args = updated_args
        return step

    def _extract_path(self, data: Any, path: str) -> Any:
        """Navigate dot-separated path through nested dict/list."""
        keys = path.split(".")
        current = data
        for key in keys:
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list) and key.isdigit():
                idx = int(key)
                current = current[idx] if idx < len(current) else None
            else:
                return None
        return current

    def detect_schema_mismatch(
        self,
        source_ns: str,
        target_ns: str,
        mapped_fields: Dict[str, str],
    ) -> List[str]:
        """Return list of field mapping warnings."""
        warnings = []
        mapping_key = f"{source_ns}→{target_ns}"
        known = self.FIELD_MAPPINGS.get(mapping_key, {})
        for src_field in mapped_fields:
            if src_field not in known:
                warnings.append(
                    f"Field '{src_field}' has no known mapping {source_ns}→{target_ns}"
                )
        return warnings


# ─── Workflow Planning Engine ─────────────────────────────────────────────────


class WorkflowPlanningEngine:
    """
    Generates a multi-step WorkflowPlan from:
    - Natural language intent
    - HydratedContext (connector health, memory, RLS)
    - DuplicateReport (create vs update decision)
    - ConfidenceScore (approval thresholds)

    Built-in plan templates:
    - shopify_to_salesforce_sync
    - customer_dedup_and_upsert
    - lead_enrichment
    - generic_lookup
    """

    PLAN_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
        "shopify_to_salesforce_sync": [
            {"desc": "Fetch Shopify order", "ns": "shopify", "action": "get_order",
             "output_key": "shopify_order", "strategy": "linear"},
            {"desc": "Extract customer email from order", "ns": "internal",
             "action": "extract_field", "output_key": "customer_email", "strategy": "linear"},
            {"desc": "Lookup Salesforce contact by email", "ns": "salesforce",
             "action": "get_contact", "output_key": "sf_contact", "strategy": "linear"},
            {"desc": "Duplicate detection", "ns": "internal", "action": "check_duplicate",
             "output_key": "dup_report", "strategy": "linear"},
            {"desc": "Confidence scoring", "ns": "internal", "action": "score_confidence",
             "output_key": "confidence", "strategy": "linear"},
            {"desc": "Create or update Salesforce contact", "ns": "salesforce",
             "action": "upsert_contact", "output_key": "sf_result",
             "strategy": "conditional", "requires_approval": True},
            {"desc": "Write audit log", "ns": "internal", "action": "write_audit_log",
             "output_key": "audit", "strategy": "linear"},
        ],
        "customer_dedup_and_upsert": [
            {"desc": "Lookup existing CRM contacts", "ns": "salesforce",
             "action": "query_contacts", "output_key": "existing", "strategy": "linear"},
            {"desc": "Run duplicate detection", "ns": "internal",
             "action": "check_duplicate", "output_key": "dup_report", "strategy": "linear"},
            {"desc": "Score match confidence", "ns": "internal",
             "action": "score_confidence", "output_key": "confidence", "strategy": "linear"},
            {"desc": "Create or merge contact", "ns": "salesforce",
             "action": "upsert_contact", "output_key": "result",
             "strategy": "conditional", "requires_approval": True},
            {"desc": "Audit log", "ns": "internal",
             "action": "write_audit_log", "output_key": "audit", "strategy": "linear"},
        ],
        "generic_lookup": [
            {"desc": "Lookup record", "ns": "salesforce",
             "action": "get_account", "output_key": "result", "strategy": "linear"},
        ],
    }

    def __init__(
        self,
        tool_selector: ToolSelectionEngine,
        reasoner: CrossConnectorReasoner,
        scorer: ConfidenceScoringEngine,
    ):
        self.tool_selector = tool_selector
        self.reasoner = reasoner
        self.scorer = scorer

    def plan(
        self,
        intent: str,
        context: HydratedContext,
        input_args: Dict[str, Any],
        duplicate_report: Optional[DuplicateReport] = None,
    ) -> WorkflowPlan:
        """Generate a WorkflowPlan from intent and context."""
        t0 = time.monotonic()

        # Select template
        template_key, template = self._select_template(intent)
        logger.info(f"[Planner] Selected template: {template_key} for intent: {intent[:80]}")

        steps: List[PlanStep] = []
        connectors: set = set()
        policy_flags: List[str] = []

        for i, tmpl in enumerate(template):
            tool = ToolRef(namespace=tmpl["ns"], action=tmpl["action"])
            connectors.add(tmpl["ns"])

            # Merge input_args for first step, use references for later
            step_args = dict(input_args) if i == 0 else {}

            # Inject cross-connector references
            if i > 0 and steps:
                prev_step = steps[-1]
                if prev_step.output_key:
                    step_args = self._build_step_args(
                        tool, tmpl["action"], prev_step, step_args
                    )

            # Policy flags
            if tmpl.get("requires_approval"):
                policy_flags.append(f"APPROVAL_REQUIRED:{tool.full_name}")

            # Adjust based on duplicate report
            requires_approval = tmpl.get("requires_approval", False)
            if (duplicate_report and tmpl["action"] in ("upsert_contact", "upsert_account")):
                if duplicate_report.resolution == DuplicateResolution.ESCALATE:
                    requires_approval = True
                    policy_flags.append("DUPLICATE_ESCALATION")

            step = PlanStep(
                step_index=i,
                tool=tool,
                description=tmpl["desc"],
                args=step_args,
                strategy=ReasoningStrategy(tmpl.get("strategy", "linear")),
                requires_approval=requires_approval,
                output_key=tmpl.get("output_key"),
            )
            steps.append(step)

        # Score the overall plan
        reliabilities = {
            ns: context.connector_contexts.get(ns, ConnectorContext(namespace=ns)).latency_p99_ms
            for ns in connectors
        }
        connector_rel = {}
        for ns in connectors:
            ctx = context.connector_contexts.get(ns)
            if ctx:
                err = ctx.error_rate_pct / 100.0
                connector_rel[ns] = round((1.0 - min(err, 1.0)) * (
                    1.0 if ctx.latency_p99_ms < 500 else 0.7
                ), 4)
            else:
                connector_rel[ns] = 0.80

        plan = WorkflowPlan(
            intent=intent,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            steps=steps,
            connectors_involved=list(connectors),
            policy_flags=policy_flags,
            planning_latency_ms=round((time.monotonic() - t0) * 1000, 2),
        )
        confidence = self.scorer.score_plan(plan, context, connector_rel)
        plan.overall_confidence = confidence.overall
        plan.estimated_duration_seconds = sum(
            s.timeout_seconds for s in steps
        )

        logger.info(
            f"[Planner] Plan {plan.plan_id}: {len(steps)} steps, "
            f"confidence={plan.overall_confidence:.2%}, "
            f"connectors={list(connectors)}"
        )
        return plan

    def _select_template(
        self, intent: str
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Select the best template based on intent keywords."""
        intent_lower = intent.lower()
        if "shopify" in intent_lower and ("salesforce" in intent_lower or "sync" in intent_lower):
            return "shopify_to_salesforce_sync", self.PLAN_TEMPLATES["shopify_to_salesforce_sync"]
        if "duplicate" in intent_lower or "dedup" in intent_lower or "upsert" in intent_lower:
            return "customer_dedup_and_upsert", self.PLAN_TEMPLATES["customer_dedup_and_upsert"]
        return "generic_lookup", self.PLAN_TEMPLATES["generic_lookup"]

    def _build_step_args(
        self,
        tool: ToolRef,
        action: str,
        prev_step: PlanStep,
        base_args: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build step args, pulling from previous step's output_key."""
        args = dict(base_args)
        if prev_step.output_key:
            if action in ("check_duplicate", "score_confidence"):
                args["source_data"] = f"{{{prev_step.output_key}}}"
            elif action == "upsert_contact":
                args["contact_data"] = f"{{{prev_step.output_key}}}"
            elif action == "write_audit_log":
                args["entity_id"] = f"{{{prev_step.output_key}.id}}"
                args["action"] = action
        return args


# ─── Rollback-Aware Execution Planner ────────────────────────────────────────


class RollbackAwareExecutionPlanner:
    """
    Annotates a WorkflowPlan with rollback specifications and manages
    checkpoint-based rollback during execution.

    Strategy:
    - PARTIAL: roll back from failure point backward through write steps
    - FULL: roll back all completed steps in reverse order
    - CHECKPOINT: roll back to the last successful write checkpoint
    - NONE: no rollback (read-only or idempotent plan)
    """

    # Actions that can be rolled back and their inverse tools
    ROLLBACK_MAP: Dict[str, Tuple[str, str]] = {
        "create_contact": ("salesforce", "delete_contact"),
        "create_account": ("salesforce", "delete_account"),
        "create_lead": ("salesforce", "delete_lead"),
        "update_contact": ("salesforce", "update_contact"),   # re-apply original
        "update_account": ("salesforce", "update_account"),
        "upsert_contact": ("salesforce", "delete_contact"),
        "upsert_account": ("salesforce", "delete_account"),
    }

    def annotate(self, plan: WorkflowPlan) -> WorkflowPlan:
        """Attach RollbackSpec to each reversible step in the plan."""
        for step in plan.steps:
            action = step.tool.action
            if action in self.ROLLBACK_MAP:
                rb_ns, rb_action = self.ROLLBACK_MAP[action]
                step.rollback = RollbackSpec(
                    tool=ToolRef(namespace=rb_ns, action=rb_action),
                    args_template={
                        "record_id": f"{{{step.output_key}.id}}" if step.output_key else "",
                        "original_state": f"{{{step.output_key}.original}}",
                    },
                    condition="on_failure",
                )
        return plan

    async def execute_rollback(
        self,
        plan: WorkflowPlan,
        failed_step: PlanStep,
        connector_executor,  # callable(tool, args) → result
    ) -> List[str]:
        """
        Execute rollback for completed write steps, starting from failed_step
        and going backward.

        Returns list of rollback messages.
        """
        messages: List[str] = []
        completed_writes = [
            s for s in plan.steps
            if s.status == PlanStepStatus.COMPLETED
            and s.rollback is not None
            and s.step_index <= failed_step.step_index
        ]
        # Reverse order
        for step in reversed(completed_writes):
            if not step.rollback:
                continue
            try:
                rb = step.rollback
                # Substitute actual result values into rollback args
                args = dict(rb.args_template)
                if step.result:
                    for k, v in args.items():
                        if isinstance(v, str) and v.startswith("{") and step.output_key:
                            field = v.strip("{}").replace(f"{step.output_key}.", "")
                            args[k] = step.result.get(field, v)

                await connector_executor(rb.tool, args)
                step.status = PlanStepStatus.ROLLED_BACK
                msg = f"Rolled back step {step.step_index} ({step.tool.full_name})"
                messages.append(msg)
                logger.info(f"[Rollback] {msg}")
            except Exception as e:
                msg = f"Rollback failed for step {step.step_index}: {e}"
                messages.append(msg)
                logger.error(f"[Rollback] {msg}")

        return messages

    def determine_strategy(self, plan: WorkflowPlan) -> RollbackStrategy:
        """Auto-determine the best rollback strategy for a plan."""
        write_steps = [
            s for s in plan.steps
            if s.tool.action in self.ROLLBACK_MAP
        ]
        if not write_steps:
            return RollbackStrategy.NONE
        if len(write_steps) == 1:
            return RollbackStrategy.PARTIAL
        return RollbackStrategy.CHECKPOINT
