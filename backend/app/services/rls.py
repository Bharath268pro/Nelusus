"""Row-Level Security (RLS) validation and enforcement service"""

import logging
from typing import Optional, List, Dict, Any
from app.models.security import UserContext, RowLevelSecurityPolicy, AuthorizationResult

logger = logging.getLogger(__name__)


class RowLevelSecurityService:
    """
    Enforces Row-Level Security policies.
    Validates that users can only access rows they're authorized to view.
    """

    def __init__(self):
        """Initialize RLS service"""
        pass

    def check_row_access(
        self,
        user_context: UserContext,
        resource_type: str,
        row_id: str,
    ) -> AuthorizationResult:
        """
        Check if user can access a specific row.

        Args:
            user_context: User security context
            resource_type: Type of resource (Account, Contact, etc.)
            row_id: ID of the row to access

        Returns:
            AuthorizationResult with authorization decision and redaction rules
        """
        # Find applicable RLS policies
        applicable_policies = [
            p for p in user_context.rls_policies if p.resource == resource_type
        ]

        if not applicable_policies:
            # No RLS policy means access is allowed
            return AuthorizationResult(
                authorized=True,
                reason="No RLS policy found for this resource",
            )

        # Check all applicable policies (all must allow access)
        for policy in applicable_policies:
            if not self._policy_allows_access(policy, row_id):
                return AuthorizationResult(
                    authorized=False,
                    reason=f"RLS policy {policy.policy_id} denies access to row {row_id}",
                    rls_policy_applied=policy.policy_id,
                )

        # Collect redaction rules from all applicable policies
        redaction_rules = []
        for policy in applicable_policies:
            redaction_rules.extend(policy.pii_fields)

        return AuthorizationResult(
            authorized=True,
            rls_policy_applied=(
                applicable_policies[0].policy_id if applicable_policies else None
            ),
            redaction_rules=list(set(redaction_rules)),  # Deduplicate
        )

    def _policy_allows_access(
        self, policy: RowLevelSecurityPolicy, row_id: str
    ) -> bool:
        """
        Evaluate a single RLS policy against a row ID.

        Args:
            policy: RLS policy
            row_id: Row ID to check

        Returns:
            True if the policy allows access
        """
        # Check explicit whitelist first
        if policy.allowed_row_ids:
            return row_id in policy.allowed_row_ids

        # Check explicit blacklist
        if policy.denied_row_ids:
            return row_id not in policy.denied_row_ids

        # Check filter conditions (simplified - in production, query against the actual data)
        if policy.filter_conditions:
            # TODO: Implement actual filter evaluation against Salesforce data
            logger.debug(
                f"Evaluating filter conditions for row {row_id}: {policy.filter_conditions}"
            )
            return True

        return True

    def redact_record(
        self,
        record: Dict[str, Any],
        redaction_rules: List[str],
    ) -> Dict[str, Any]:
        """
        Redact PII fields from a record based on rules.

        Args:
            record: The record to redact
            redaction_rules: List of field names to redact

        Returns:
            Redacted copy of the record
        """
        redacted = record.copy()

        for field in redaction_rules:
            if field in redacted:
                # Replace with masked value
                redacted[field] = self._mask_value(redacted[field])

        return redacted

    @staticmethod
    def _mask_value(value: Any) -> str:
        """
        Mask a value (for PII redaction).

        Args:
            value: Value to mask

        Returns:
            Masked representation
        """
        if isinstance(value, str):
            if len(value) <= 4:
                return "*" * len(value)
            # Show first and last characters
            return value[0] + "*" * (len(value) - 2) + value[-1]
        return "[REDACTED]"
