"""OAuth and scope validation service with Redis caching"""

import json
import logging
from typing import Optional, List
from datetime import datetime, timedelta
import httpx
from app.models.security import UserContext, OAuthScope, RowLevelSecurityPolicy
from app.models.mcp_protocol import ToolStatus
from app.config import settings

logger = logging.getLogger(__name__)


class OAuthService:
    """
    Manages OAuth scope validation with Redis caching.
    Provides < 50ms overhead for token validation.
    """

    SCOPE_CACHE_TTL = 300  # 5 minutes
    TOKEN_CACHE_TTL = 3600  # 1 hour

    def __init__(self, redis_client=None):
        """Initialize OAuth service with optional Redis client"""
        self.redis = redis_client
        self.http_client = httpx.AsyncClient()

    async def validate_scope(self, user_id: str, required_scope: str) -> bool:
        """
        Check if user has the required OAuth scope.

        Args:
            user_id: User identifier
            required_scope: Scope to check (e.g., 'sfdc:read_account')

        Returns:
            True if user has the scope
        """
        user_context = await self.get_user_context(user_id)
        if not user_context:
            return False

        user_scopes = [scope.scope for scope in user_context.scopes]
        return required_scope in user_scopes

    async def validate_scopes(
        self, user_id: str, required_scopes: List[str]
    ) -> tuple[bool, Optional[str]]:
        """
        Check if user has all required OAuth scopes.

        Args:
            user_id: User identifier
            required_scopes: List of scopes required

        Returns:
            Tuple of (authorized: bool, missing_scope: Optional[str])
        """
        for scope in required_scopes:
            if not await self.validate_scope(user_id, scope):
                return False, scope
        return True, None

    async def get_user_context(self, user_id: str) -> Optional[UserContext]:
        """
        Get cached or fetched user context with OAuth scopes.

        Args:
            user_id: User identifier

        Returns:
            UserContext with scopes and RLS policies, or None if not found
        """
        # Try cache first
        if self.redis:
            cached = await self._get_cached_context(user_id)
            if cached:
                return cached

        # Fetch from Auth0/Okta
        context = await self._fetch_user_context(user_id)

        # Cache result
        if context and self.redis:
            await self._cache_context(user_id, context)

        return context

    async def _get_cached_context(self, user_id: str) -> Optional[UserContext]:
        """Retrieve user context from Redis cache"""
        try:
            key = f"user_context:{user_id}"
            cached_data = await self.redis.get(key)
            if cached_data:
                data = json.loads(cached_data)
                return UserContext(**data)
        except Exception as e:
            logger.error(f"Cache retrieval error: {e}")
        return None

    async def _cache_context(self, user_id: str, context: UserContext) -> None:
        """Store user context in Redis cache"""
        try:
            key = f"user_context:{user_id}"
            await self.redis.setex(
                key,
                self.SCOPE_CACHE_TTL,
                context.model_dump_json(),
            )
        except Exception as e:
            logger.error(f"Cache storage error: {e}")

    async def _fetch_user_context(self, user_id: str) -> Optional[UserContext]:
        """
        Fetch user context from Auth0/Okta with scopes and policies.
        This is a placeholder - implement with your auth provider's API.
        """
        try:
            # TODO: Implement actual Auth0/Okta API call
            # Example: Call GET /api/v2/users/{user_id}
            # Include custom claims for scopes and RLS policies
            logger.info(f"Fetching user context for {user_id}")

            # Placeholder implementation
            return UserContext(
                user_id=user_id,
                email=f"user_{user_id}@example.com",
                organization_id="org_123",
                scopes=[
                    OAuthScope(
                        scope="sfdc:read_account",
                        resource="Account",
                        actions=["read"],
                    ),
                    OAuthScope(
                        scope="sfdc:read_contact",
                        resource="Contact",
                        actions=["read"],
                    ),
                ],
                rls_policies=[],
                groups=["salesforce-users"],
            )
        except Exception as e:
            logger.error(f"Failed to fetch user context: {e}")
            return None

    async def get_tool_status(
        self, user_id: str, tool_name: str, resource_id: Optional[str] = None
    ) -> ToolStatus:
        """
        Determine if a tool is available to the user.

        Args:
            user_id: User identifier
            tool_name: Name of the tool (e.g., 'read_salesforce_account')
            resource_id: Optional specific resource ID for RLS check

        Returns:
            ToolStatus indicating availability
        """
        # Extract required scope from tool name
        scope_mapping = {
            "read_salesforce_account": "sfdc:read_account",
            "read_salesforce_contact": "sfdc:read_contact",
            "write_salesforce_account": "sfdc:write_account",
        }

        required_scope = scope_mapping.get(tool_name)
        if not required_scope:
            return ToolStatus.AVAILABLE

        authorized, _ = await self.validate_scopes(user_id, [required_scope])
        return ToolStatus.AVAILABLE if authorized else ToolStatus.DENIED

    async def close(self) -> None:
        """Cleanup resources"""
        await self.http_client.aclose()
