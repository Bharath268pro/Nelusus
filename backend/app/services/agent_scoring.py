"""Phase 2D: Confidence Scoring Engine + Duplicate Resolution Engine

ConfidenceScoringEngine  – multi-dimensional confidence scoring
DuplicateResolutionEngine – fuzzy matching, normalization, tenant-aware isolation
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from app.models.orchestration import (
    CandidateMatch,
    ConfidenceScore,
    ConfidenceTier,
    DuplicateReport,
    DuplicateResolution,
    HydratedContext,
    WorkflowPlan,
)

logger = logging.getLogger(__name__)


# ─── Confidence Scoring Engine ────────────────────────────────────────────────


class ConfidenceScoringEngine:
    """
    Produces multi-dimensional ConfidenceScore for:
    - Plan viability (will the plan succeed?)
    - Entity match quality (is this the right record?)
    - Duplicate resolution decisions

    Dimensions:
    entity_match        – how well the entity fields matched
    schema_completeness – coverage of required fields
    connector_reliability – historical uptime of involved connectors
    policy_risk         – inverse of mutation risk
    duplicate_likelihood – probability a duplicate exists
    historical_success  – past success rate for this tool/intent
    """

    # Risk weights: higher risk → lower policy_risk score
    _RISK_WEIGHTS = {
        "delete": 0.10, "cancel": 0.15, "bulk_delete": 0.05,
        "void": 0.15, "refund": 0.20,
        "create": 0.60, "update": 0.70, "patch": 0.75,
        "get": 0.95, "list": 0.95, "query": 0.95,
    }

    def score_plan(
        self,
        plan: WorkflowPlan,
        context: HydratedContext,
        connector_reliabilities: Dict[str, float],
    ) -> ConfidenceScore:
        """Score the overall viability of a workflow plan."""
        # Schema completeness: avg of all steps' arg coverage
        completeness = self._plan_completeness(plan)

        # Connector reliability: min across all involved connectors
        reliability = min(
            (connector_reliabilities.get(ns, 0.80) for ns in plan.connectors_involved),
            default=0.80,
        )

        # Policy risk: min risk score across all write steps
        policy = self._plan_policy_risk(plan)

        # Historical success (stub — production: query metrics store)
        hist = 0.80

        # Entity match: N/A at plan level
        entity = 0.85

        # Duplicate likelihood at plan level: 0 = no duplicate concern
        dup_likelihood = 1.0  # 1.0 means no duplicate risk

        return ConfidenceScore(
            entity_match=entity,
            schema_completeness=completeness,
            connector_reliability=reliability,
            policy_risk=policy,
            duplicate_likelihood=dup_likelihood,
            historical_success=hist,
        )

    def score_entity_match(
        self,
        incoming: Dict[str, Any],
        candidate: Dict[str, Any],
        match_fields: List[str],
    ) -> ConfidenceScore:
        """Score how well an incoming entity matches a candidate record."""
        field_scores = []
        for field in match_fields:
            inc_val = str(incoming.get(field, "")).strip().lower()
            can_val = str(candidate.get(field, "")).strip().lower()
            if inc_val and can_val:
                score = SequenceMatcher(None, inc_val, can_val).ratio()
                field_scores.append(score)

        entity_match = round(
            sum(field_scores) / len(field_scores) if field_scores else 0.0, 4
        )

        # Schema completeness: how many match_fields both have
        both_present = sum(
            1 for f in match_fields
            if incoming.get(f) and candidate.get(f)
        )
        completeness = round(both_present / max(len(match_fields), 1), 4)

        return ConfidenceScore(
            entity_match=entity_match,
            schema_completeness=completeness,
            connector_reliability=0.90,
            policy_risk=0.80,
            duplicate_likelihood=entity_match,  # high match → high dup likelihood
            historical_success=0.80,
        )

    def score_connector_step(
        self,
        tool_name: str,
        args: Dict[str, Any],
        required_fields: List[str],
        connector_reliability: float,
    ) -> ConfidenceScore:
        """Score a single tool step's viability."""
        present = sum(1 for f in required_fields if args.get(f))
        completeness = round(present / max(len(required_fields), 1), 4)
        action = tool_name.split(".")[-1].lower() if "." in tool_name else tool_name
        policy = self._action_risk(action)
        return ConfidenceScore(
            entity_match=0.85,
            schema_completeness=completeness,
            connector_reliability=connector_reliability,
            policy_risk=policy,
            duplicate_likelihood=0.90,
            historical_success=0.80,
        )

    def _plan_completeness(self, plan: WorkflowPlan) -> float:
        scores = []
        for step in plan.steps:
            arg_count = len(step.args)
            filled = sum(1 for v in step.args.values() if v is not None and v != "")
            scores.append(filled / max(arg_count, 1))
        return round(sum(scores) / max(len(scores), 1), 4)

    def _plan_policy_risk(self, plan: WorkflowPlan) -> float:
        scores = []
        for step in plan.steps:
            action = step.tool.action.lower()
            scores.append(self._action_risk(action))
        return round(min(scores, default=0.80), 4)

    def _action_risk(self, action: str) -> float:
        for keyword, score in self._RISK_WEIGHTS.items():
            if action.startswith(keyword):
                return score
        return 0.65  # unknown action — moderate risk


# ─── Duplicate Resolution Engine ─────────────────────────────────────────────


class DuplicateResolutionEngine:
    """
    Detects and resolves duplicate entities across connectors.

    Features:
    - Email normalization (plus-addressing, dots in Gmail)
    - Phone normalization (E.164)
    - Name fuzzy matching (SequenceMatcher)
    - Tenant-aware isolation (never match across tenants)
    - Weighted similarity scoring
    - Configurable resolution policy
    """

    # Minimum similarity to consider a candidate match
    MATCH_THRESHOLD = 0.72
    # Minimum similarity to auto-resolve (below → escalate)
    AUTO_RESOLVE_THRESHOLD = 0.88

    def detect(
        self,
        incoming: Dict[str, Any],
        existing_records: List[Dict[str, Any]],
        tenant_id: str,
        object_type: str = "Contact",
        namespace: str = "salesforce",
    ) -> DuplicateReport:
        """
        Compare an incoming entity against a list of existing records.
        Returns a DuplicateReport with candidates and resolution recommendation.
        """
        fingerprint = self._fingerprint(incoming)
        candidates: List[CandidateMatch] = []

        for record in existing_records:
            # Tenant isolation: skip records from other tenants
            if record.get("tenant_id") and record["tenant_id"] != tenant_id:
                continue

            score, reasons, conflicts = self._similarity(incoming, record)
            if score >= self.MATCH_THRESHOLD:
                candidates.append(CandidateMatch(
                    record_id=str(record.get("id", record.get("Id", "unknown"))),
                    namespace=namespace,
                    object_type=object_type,
                    similarity_score=round(score, 4),
                    match_reasons=reasons,
                    conflicting_fields=conflicts,
                    metadata={k: record[k] for k in ("name", "email", "phone")
                              if k in record},
                ))

        # Sort by score descending
        candidates.sort(key=lambda c: c.similarity_score, reverse=True)

        resolution, confidence, reasoning = self._resolve(candidates)

        return DuplicateReport(
            entity_fingerprint=fingerprint,
            candidates=candidates,
            resolution=resolution,
            confidence=round(confidence, 4),
            recommended_record_id=candidates[0].record_id if candidates else None,
            reasoning=reasoning,
        )

    def normalize_email(self, email: str) -> str:
        """
        Normalize email for comparison:
        - lowercase
        - remove Gmail dots in local part
        - strip plus-addressing
        """
        email = email.strip().lower()
        if "@" not in email:
            return email
        local, domain = email.rsplit("@", 1)
        # Strip plus-addressing
        local = local.split("+")[0]
        # Remove dots in Gmail local part
        if domain in ("gmail.com", "googlemail.com"):
            local = local.replace(".", "")
        return f"{local}@{domain}"

    def normalize_phone(self, phone: str) -> str:
        """Strip all non-digits, keep last 10 digits (US normalization)."""
        digits = re.sub(r"\D", "", phone)
        if len(digits) > 10:
            digits = digits[-10:]
        return digits

    def normalize_name(self, name: str) -> str:
        """Normalize unicode, lowercase, strip extra whitespace."""
        name = unicodedata.normalize("NFKD", name)
        name = re.sub(r"\s+", " ", name.strip().lower())
        return name

    def _fingerprint(self, entity: Dict[str, Any]) -> str:
        """Create a stable fingerprint of the incoming entity."""
        parts = []
        for key in sorted(entity.keys()):
            val = entity[key]
            if isinstance(val, str) and val:
                parts.append(f"{key}:{val.strip().lower()}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def _similarity(
        self,
        incoming: Dict[str, Any],
        existing: Dict[str, Any],
    ) -> Tuple[float, List[str], List[str]]:
        """
        Compute similarity score between incoming and existing record.
        Returns: (score, match_reasons, conflicting_fields)
        """
        scores: List[Tuple[float, float]] = []  # (score, weight)
        reasons: List[str] = []
        conflicts: List[str] = []

        # Email (highest weight)
        inc_email = self.normalize_email(incoming.get("email", ""))
        ex_email = self.normalize_email(existing.get("email", ""))
        if inc_email and ex_email:
            if inc_email == ex_email:
                scores.append((1.0, 0.40))
                reasons.append(f"Email exact match: {inc_email}")
            else:
                s = SequenceMatcher(None, inc_email, ex_email).ratio()
                scores.append((s, 0.40))
                if s < 0.80:
                    conflicts.append("email")

        # Phone
        inc_phone = self.normalize_phone(incoming.get("phone", ""))
        ex_phone = self.normalize_phone(existing.get("phone", ""))
        if inc_phone and ex_phone:
            if inc_phone == ex_phone:
                scores.append((1.0, 0.25))
                reasons.append(f"Phone exact match: {inc_phone}")
            else:
                s = SequenceMatcher(None, inc_phone, ex_phone).ratio()
                scores.append((s, 0.25))
                if s < 0.70:
                    conflicts.append("phone")

        # Name
        inc_name = self.normalize_name(
            incoming.get("name", incoming.get("full_name", ""))
        )
        ex_name = self.normalize_name(
            existing.get("name", existing.get("full_name", ""))
        )
        if inc_name and ex_name:
            s = SequenceMatcher(None, inc_name, ex_name).ratio()
            scores.append((s, 0.25))
            if s >= 0.85:
                reasons.append(f"Name fuzzy match: {s:.0%}")
            elif s < 0.60:
                conflicts.append("name")

        # Company / Account
        inc_co = self.normalize_name(
            incoming.get("company", incoming.get("account_name", ""))
        )
        ex_co = self.normalize_name(
            existing.get("company", existing.get("account_name", ""))
        )
        if inc_co and ex_co:
            s = SequenceMatcher(None, inc_co, ex_co).ratio()
            scores.append((s, 0.10))
            if s >= 0.85:
                reasons.append(f"Company match: {s:.0%}")

        if not scores:
            return 0.0, [], []

        total_weight = sum(w for _, w in scores)
        weighted_score = sum(s * w for s, w in scores) / total_weight
        return weighted_score, reasons, conflicts

    def _resolve(
        self, candidates: List[CandidateMatch]
    ) -> Tuple[DuplicateResolution, float, List[str]]:
        """Determine resolution strategy based on candidates."""
        if not candidates:
            return DuplicateResolution.CREATE_NEW, 0.95, [
                "No existing records matched — safe to create"
            ]

        best = candidates[0]
        score = best.similarity_score
        reasoning: List[str] = [f"Best candidate: {best.record_id} (score={score:.0%})"]
        reasoning.extend(best.match_reasons)

        if score >= self.AUTO_RESOLVE_THRESHOLD:
            if best.conflicting_fields:
                reasoning.append(
                    f"Conflicting fields: {best.conflicting_fields} — updating"
                )
                return DuplicateResolution.UPDATE_EXISTING, score, reasoning
            return DuplicateResolution.UPDATE_EXISTING, score, reasoning

        elif score >= self.MATCH_THRESHOLD:
            reasoning.append(
                f"Score {score:.0%} is in ambiguous range — human escalation required"
            )
            if len(candidates) > 1:
                reasoning.append(
                    f"{len(candidates)} candidates found — possible merge needed"
                )
            return DuplicateResolution.ESCALATE, score, reasoning

        return DuplicateResolution.CREATE_NEW, 1.0 - score, [
            "No confident match found"
        ]
