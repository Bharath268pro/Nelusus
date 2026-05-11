"""Security models for JWT, OAuth, and Row-Level Security"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime


class OAuthScope(BaseModel):
    """Represents an OAuth scope authorized for a user"""

    scope: str = Field(..., description="Scope name (e.g., 'sfdc:read_account')")
    resource: str = Field(..., description="Resource this scope applies to")
    actions: List[str] = Field(default=["read"], description="Actions allowed (read, write, delete)")
    row_level_security: Optional[Dict[str, Any]] = Field(
        None, description="RLS policy for this scope"
    )
    granted_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = Field(None, description="When this scope expires")


class RowLevelSecurityPolicy(BaseModel):
    """Defines what rows a user can access for a resource"""

    policy_id: str = Field(..., description="Unique policy identifier")
    resource: str = Field(..., description="Resource name (e.g., 'Account')")
    policy_type: str = Field(
        default="field_based", description="Type of RLS (field_based, rule_based, whitelist)"
    )
    filter_conditions: Dict[str, Any] = Field(
        ..., description="Filter conditions to apply (e.g., {'OwnerId': 'user123', 'Status': 'Active'})"
    )
    allowed_row_ids: Optional[List[str]] = Field(None, description="Explicit whitelist of row IDs")
    denied_row_ids: Optional[List[str]] = Field(None, description="Explicit blacklist of row IDs")
    pii_fields: List[str] = Field(default=[], description="Fields considered PII and subject to redaction")


class UserContext(BaseModel):
    """Security context for an authenticated user"""

    user_id: str = Field(..., description="Unique user identifier")
    email: str = Field(..., description="User's email")
    organization_id: str = Field(..., description="Organization/Tenant ID")
    scopes: List[OAuthScope] = Field(default=[], description="Authorized OAuth scopes")
    rls_policies: List[RowLevelSecurityPolicy] = Field(
        default=[], description="Row-level security policies"
    )
    groups: List[str] = Field(default=[], description="User's groups/roles")
    authenticated_at: datetime = Field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = Field(None, description="IP address of the request")
    user_agent: Optional[str] = Field(None, description="User agent string")
    is_service_account: bool = Field(default=False, description="Whether this is a service account")


class JWTToken(BaseModel):
    """JWT Token payload structure"""

    sub: str = Field(..., description="Subject (user ID)")
    iss: str = Field(..., description="Issuer")
    aud: str = Field(..., description="Audience")
    exp: int = Field(..., description="Expiration timestamp")
    iat: int = Field(..., description="Issued at timestamp")
    email: Optional[str] = Field(None, description="User email")
    org_id: Optional[str] = Field(None, description="Organization ID")
    scopes: List[str] = Field(default=[], description="OAuth scopes")
    custom_claims: Dict[str, Any] = Field(default={}, description="Custom claims")


class AuthorizationResult(BaseModel):
    """Result of an authorization check"""

    authorized: bool = Field(..., description="Whether the action is authorized")
    reason: Optional[str] = Field(None, description="Reason for denial")
    scope_required: Optional[str] = Field(None, description="Scope that was required")
    rls_policy_applied: Optional[str] = Field(None, description="RLS policy that was applied")
    redaction_rules: List[str] = Field(default=[], description="PII fields to redact")
