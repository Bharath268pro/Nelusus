"""Tests for RLS service"""

import pytest
from app.models.security import UserContext, RowLevelSecurityPolicy
from app.services.rls import RowLevelSecurityService


def test_no_rls_policy_allows_access():
    """Test that access is allowed when no RLS policy exists"""
    service = RowLevelSecurityService()
    user_context = UserContext(user_id="user1", email="test@example.com", organization_id="org1")

    result = service.check_row_access(user_context, "Account", "acc123")
    assert result.authorized is True


def test_whitelist_policy():
    """Test RLS with explicit whitelist"""
    service = RowLevelSecurityService()

    policy = RowLevelSecurityPolicy(
        policy_id="policy1",
        resource="Account",
        policy_type="whitelist",
        filter_conditions={},
        allowed_row_ids=["acc1", "acc2", "acc3"],
    )

    user_context = UserContext(
        user_id="user1",
        email="test@example.com",
        organization_id="org1",
        rls_policies=[policy],
    )

    # Allowed
    result = service.check_row_access(user_context, "Account", "acc1")
    assert result.authorized is True

    # Not allowed
    result = service.check_row_access(user_context, "Account", "acc999")
    assert result.authorized is False


def test_pii_redaction():
    """Test PII field redaction"""
    service = RowLevelSecurityService()
    record = {"name": "John Doe", "email": "john@example.com", "phone": "5551234567"}

    redacted = service.redact_record(record, ["email", "phone"])
    assert redacted["name"] == "John Doe"
    assert "john@example.com" not in redacted["email"]
    assert "5551234567" not in redacted["phone"]
