"""JWT validation and authentication module for RS256 tokens"""

import logging
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime
from app.models.jsonrpc import Identity
from app.config import Settings
from app.utils.cache import RedisCache, RedisKeyBuilder
import httpx
from jose import jwt, JWTError
from jose.exceptions import JWTClaimsError

logger = logging.getLogger(__name__)


class JWKSFetcher:
    """Fetches and caches JWKS from provider"""

    def __init__(self, cache: Optional[RedisCache], settings: Settings):
        self.cache = cache
        self.settings = settings
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_client_timeout_seconds)
        )

    async def fetch_jwks(self, issuer: str) -> Optional[Dict[str, Any]]:
        """Fetch JWKS from issuer, with cache fallback"""
        # Try cache first
        if self.cache:
            cached_jwks = await self.cache.get_jwks(issuer)
            if cached_jwks:
                logger.debug(f"JWKS cache hit for issuer: {issuer}")
                return cached_jwks

        # Fetch from JWKS URI
        try:
            logger.debug(f"Fetching JWKS from {self.settings.oauth2_jwks_endpoint}")
            response = await self.http_client.get(self.settings.oauth2_jwks_endpoint)
            response.raise_for_status()
            jwks = response.json()

            # Cache the JWKS
            if self.cache:
                await self.cache.set_jwks(issuer, jwks)

            logger.debug(f"Successfully fetched JWKS for issuer: {issuer}")
            return jwks
        except Exception as e:
            logger.error(f"Failed to fetch JWKS from {self.settings.oauth2_jwks_endpoint}: {e}")
            return None

    async def get_key(self, issuer: str, kid: str) -> Optional[Dict[str, Any]]:
        """Get a specific key from JWKS by key ID (kid)"""
        jwks = await self.fetch_jwks(issuer)
        if not jwks:
            return None

        # Find key with matching kid
        keys = jwks.get("keys", [])
        for key in keys:
            if key.get("kid") == kid:
                return key

        logger.warning(f"Key ID {kid} not found in JWKS for issuer {issuer}")
        return None

    async def close(self) -> None:
        """Close HTTP client"""
        await self.http_client.aclose()


class JWTValidator:
    """Validates RS256 JWT tokens and extracts identity claims"""

    def __init__(self, cache: Optional[RedisCache], settings: Settings):
        self.cache = cache
        self.settings = settings
        self.jwks_fetcher = JWKSFetcher(cache, settings)

    async def validate_token(self, token: str) -> Optional[Identity]:
        """Validate JWT token and return Identity object"""
        try:
            # Decode without verification first to get headers
            unverified = jwt.get_unverified_claims(token)
            headers = jwt.get_unverified_header(token)

            # Extract key ID
            kid = headers.get("kid")
            if not kid:
                logger.warning("Missing 'kid' in JWT header")
                return None

            # Get the key from JWKS
            key = await self.jwks_fetcher.get_key(self.settings.jwt_issuer, kid)
            if not key:
                logger.warning(f"Unable to find key with kid: {kid}")
                return None

            # Verify token with RS256
            claims = jwt.decode(
                token,
                key,
                algorithms=[self.settings.jwt_algorithm],
                issuer=self.settings.jwt_issuer,
                audience=self.settings.jwt_audience,
                options={
                    "leeway": self.settings.jwt_leeway_seconds,
                    "verify_signature": True,
                    "verify_iss": True,
                    "verify_aud": True,
                    "verify_exp": True,
                },
            )

            logger.debug(f"Token validated successfully for user: {claims.get('sub')}")

            # Extract identity from claims
            identity = Identity(
                sub=claims.get("sub", ""),
                tenant_id=claims.get("tenant_id", claims.get("org_id", "")),
                sf_user_id=claims.get("sf_user_id"),
                scopes=claims.get("scopes", claims.get("scope", "").split()),
                roles=claims.get("roles", []),
                email=claims.get("email"),
                iss=claims.get("iss"),
                aud=claims.get("aud"),
                iat=claims.get("iat"),
                exp=claims.get("exp"),
                nbf=claims.get("nbf"),
            )

            return identity

        except JWTClaimsError as e:
            logger.warning(f"JWT claims validation failed: {e}")
            return None
        except JWTError as e:
            logger.warning(f"JWT validation failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error validating JWT: {e}")
            return None

    async def extract_bearer_token(self, auth_header: str) -> Optional[str]:
        """Extract bearer token from Authorization header"""
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            logger.warning("Invalid Authorization header format")
            return None
        return parts[1]

    async def close(self) -> None:
        """Close JWKS fetcher"""
        await self.jwks_fetcher.close()


class ScopeValidator:
    """Validates OAuth scopes in identity"""

    @staticmethod
    def validate_scope(identity: Identity, required_scope: str) -> bool:
        """Check if identity has required scope"""
        return identity.has_scope(required_scope)

    @staticmethod
    def validate_any_scope(identity: Identity, scopes: List[str]) -> bool:
        """Check if identity has any of the required scopes"""
        return identity.has_any_scope(scopes)

    @staticmethod
    def validate_all_scopes(identity: Identity, scopes: List[str]) -> bool:
        """Check if identity has all required scopes"""
        return identity.has_all_scopes(scopes)

    @staticmethod
    def map_scopes(
        identity: Identity,
        scope_mapping: Dict[str, List[str]],
    ) -> List[str]:
        """Map connector-specific scopes to identity scopes"""
        mapped_scopes = []
        for identity_scope in identity.scopes:
            if identity_scope in scope_mapping:
                mapped_scopes.extend(scope_mapping[identity_scope])
        return mapped_scopes


class OAuthClaimsExtractor:
    """Extracts custom claims from OAuth tokens"""

    @staticmethod
    def extract_tenant_id(claims: Dict[str, Any]) -> Optional[str]:
        """Extract tenant ID from claims"""
        # Try common tenant claim names
        return (
            claims.get("tenant_id")
            or claims.get("org_id")
            or claims.get("organization_id")
            or claims.get("https://your-org/tenant_id")
        )

    @staticmethod
    def extract_user_id(claims: Dict[str, Any]) -> str:
        """Extract user ID from claims"""
        return claims.get("sub", "")

    @staticmethod
    def extract_salesforce_user_id(claims: Dict[str, Any]) -> Optional[str]:
        """Extract Salesforce user ID from claims"""
        return claims.get("sf_user_id") or claims.get("salesforce_user_id")

    @staticmethod
    def extract_roles(claims: Dict[str, Any]) -> List[str]:
        """Extract roles from claims"""
        roles = claims.get("roles")
        if isinstance(roles, list):
            return roles
        if isinstance(roles, str):
            return [roles]
        return []

    @staticmethod
    def extract_scopes(claims: Dict[str, Any]) -> List[str]:
        """Extract scopes from claims"""
        scopes = claims.get("scopes") or claims.get("scope")
        if isinstance(scopes, list):
            return scopes
        if isinstance(scopes, str):
            return scopes.split()
        return []


class TokenCache:
    """Cache for token validation results"""

    def __init__(self, cache: Optional[RedisCache], settings: Settings):
        self.cache = cache
        self.settings = settings

    async def get_cached_validation(self, token: str) -> Optional[Identity]:
        """Get cached token validation result"""
        if not self.cache:
            return None

        token_hash = self._hash_token(token)
        return await self.cache.get_json(RedisKeyBuilder.token_key(token_hash))

    async def cache_validation(self, token: str, identity: Identity) -> bool:
        """Cache token validation result"""
        if not self.cache:
            return False

        token_hash = self._hash_token(token)
        return await self.cache.set_json(
            RedisKeyBuilder.token_key(token_hash),
            identity.model_dump(),
            self.settings.redis_token_ttl,
        )

    def _hash_token(self, token: str) -> str:
        """Create a secure hash of token for caching"""
        return hashlib.sha256(token.encode()).hexdigest()
