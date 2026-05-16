"""Unit tests for JWT validation and authentication"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.jwt_auth import ScopeValidator, OAuthClaimsExtractor
from app.models.jsonrpc import Identity
from app.config import Settings


@pytest.fixture
def mock_settings():
    """Create mock settings for testing"""
    settings = MagicMock(spec=Settings)
    settings.jwt_algorithm = "RS256"
    settings.jwt_issuer = "https://example.com"
    settings.jwt_audience = "nexusmcp"
    settings.jwt_leeway_seconds = 30
    settings.http_client_timeout_seconds = 10
    settings.oauth2_jwks_endpoint = "https://example.com/.well-known/jwks.json"
    settings.redis_token_ttl = 1800
    return settings


@pytest.fixture
def sample_identity():
    """Create a sample identity for testing"""
    return Identity(
        sub="user123",
        tenant_id="tenant456",
        sf_user_id="sf789",
        scopes=["read_accounts", "read_opportunities"],
        roles=["user", "power_user"],
        email="user@example.com",
    )


class TestScopeValidator:
    """Test OAuth scope validation"""

    def test_has_scope_success(self, sample_identity):
        """Test checking for existing scope"""
        assert ScopeValidator.validate_scope(sample_identity, "read_accounts") is True

    def test_has_scope_failure(self, sample_identity):
        """Test checking for missing scope"""
        assert ScopeValidator.validate_scope(sample_identity, "delete_accounts") is False

    def test_has_any_scope_success(self, sample_identity):
        """Test checking for any of multiple scopes"""
        scopes = ["delete_accounts", "read_accounts", "write_accounts"]
        assert ScopeValidator.validate_any_scope(sample_identity, scopes) is True

    def test_has_any_scope_failure(self, sample_identity):
        """Test when none of the scopes match"""
        scopes = ["delete_accounts", "write_accounts"]
        assert ScopeValidator.validate_any_scope(sample_identity, scopes) is False

    def test_has_all_scopes_success(self, sample_identity):
        """Test checking for all required scopes"""
        scopes = ["read_accounts", "read_opportunities"]
        assert ScopeValidator.validate_all_scopes(sample_identity, scopes) is True

    def test_has_all_scopes_failure(self, sample_identity):
        """Test when not all required scopes present"""
        scopes = ["read_accounts", "read_opportunities", "write_opportunities"]
        assert ScopeValidator.validate_all_scopes(sample_identity, scopes) is False


class TestOAuthClaimsExtractor:
    """Test OAuth claims extraction"""

    def test_extract_tenant_id_primary(self):
        """Test extracting tenant_id from claims"""
        claims = {"tenant_id": "tenant-123"}
        assert OAuthClaimsExtractor.extract_tenant_id(claims) == "tenant-123"

    def test_extract_tenant_id_org_id(self):
        """Test extracting from org_id fallback"""
        claims = {"org_id": "org-456"}
        assert OAuthClaimsExtractor.extract_tenant_id(claims) == "org-456"

    def test_extract_user_id(self):
        """Test extracting user ID from sub claim"""
        claims = {"sub": "user-789"}
        assert OAuthClaimsExtractor.extract_user_id(claims) == "user-789"

    def test_extract_salesforce_user_id(self):
        """Test extracting Salesforce user ID"""
        claims = {"sf_user_id": "sf-user-123"}
        assert OAuthClaimsExtractor.extract_salesforce_user_id(claims) == "sf-user-123"

    def test_extract_roles_list(self):
        """Test extracting roles as list"""
        claims = {"roles": ["admin", "user"]}
        roles = OAuthClaimsExtractor.extract_roles(claims)
        assert roles == ["admin", "user"]

    def test_extract_roles_string(self):
        """Test extracting roles as string"""
        claims = {"roles": "admin"}
        roles = OAuthClaimsExtractor.extract_roles(claims)
        assert roles == ["admin"]

    def test_extract_scopes_list(self):
        """Test extracting scopes as list"""
        claims = {"scopes": ["read", "write"]}
        scopes = OAuthClaimsExtractor.extract_scopes(claims)
        assert scopes == ["read", "write"]

    def test_extract_scopes_string(self):
        """Test extracting scopes as space-separated string"""
        claims = {"scope": "read write execute"}
        scopes = OAuthClaimsExtractor.extract_scopes(claims)
        assert scopes == ["read", "write", "execute"]

    def test_extract_scopes_empty(self):
        """Test extracting when no scopes present"""
        claims = {}
        scopes = OAuthClaimsExtractor.extract_scopes(claims)
        assert scopes == []


class TestIdentity:
    """Test Identity model"""

    def test_identity_has_scope(self, sample_identity):
        """Test Identity.has_scope method"""
        assert sample_identity.has_scope("read_accounts") is True
        assert sample_identity.has_scope("write_accounts") is False

    def test_identity_has_any_scope(self, sample_identity):
        """Test Identity.has_any_scope method"""
        assert sample_identity.has_any_scope(["write", "read_accounts"]) is True
        assert sample_identity.has_any_scope(["write", "delete"]) is False

    def test_identity_has_all_scopes(self, sample_identity):
        """Test Identity.has_all_scopes method"""
        assert sample_identity.has_all_scopes(["read_accounts", "read_opportunities"]) is True
        assert (
            sample_identity.has_all_scopes(["read_accounts", "read_opportunities", "write"])
            is False
        )

    def test_identity_serialization(self, sample_identity):
        """Test Identity model serialization"""
        data = sample_identity.model_dump()
        assert data["sub"] == "user123"
        assert data["tenant_id"] == "tenant456"
        assert len(data["scopes"]) == 2
    token = AuthenticationService.extract_bearer_token("Invalid token")
    assert token is None

    token = AuthenticationService.extract_bearer_token(None)
    assert token is None
