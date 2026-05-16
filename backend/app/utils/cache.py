"""Redis cache integration for NexusMCP gateway"""

import json
import logging
from typing import Optional, Any, Dict, List
from datetime import datetime, timedelta
from redis.asyncio import Redis, ConnectionPool
from app.config import Settings

logger = logging.getLogger(__name__)


class RedisKeyBuilder:
    """Builder for namespaced Redis keys with consistent formatting"""

    PREFIX = "nexusmcp"

    @classmethod
    def jwks_key(cls, issuer: str) -> str:
        """Key for JWKS cache (issuer-specific)"""
        safe_issuer = issuer.replace(":", "_").replace("/", "_")
        return f"{cls.PREFIX}:jwks:{safe_issuer}"

    @classmethod
    def token_key(cls, token_hash: str) -> str:
        """Key for token validation cache"""
        return f"{cls.PREFIX}:token:{token_hash}"

    @classmethod
    def tool_schema_key(cls, tool_name: str) -> str:
        """Key for tool schema cache"""
        return f"{cls.PREFIX}:tool_schema:{tool_name}"

    @classmethod
    def tool_list_key(cls, namespace: Optional[str] = None) -> str:
        """Key for cached tool list"""
        if namespace:
            return f"{cls.PREFIX}:tool_list:{namespace}"
        return f"{cls.PREFIX}:tool_list:all"

    @classmethod
    def rls_policy_key(cls, tenant_id: str, resource_type: str) -> str:
        """Key for RLS policy cache"""
        return f"{cls.PREFIX}:rls_policy:{tenant_id}:{resource_type}"

    @classmethod
    def scope_mapping_key(cls, tenant_id: str, connector_id: str) -> str:
        """Key for scope mapping cache"""
        return f"{cls.PREFIX}:scope_mapping:{tenant_id}:{connector_id}"

    @classmethod
    def user_identity_key(cls, tenant_id: str, user_id: str) -> str:
        """Key for cached user identity"""
        return f"{cls.PREFIX}:identity:{tenant_id}:{user_id}"


class RedisCache:
    """Async Redis cache client with structured interface"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.redis: Optional[Redis] = None
        self.logger = logging.getLogger(__name__)

    async def connect(self) -> None:
        """Establish Redis connection pool"""
        try:
            pool = ConnectionPool(
                host=self.settings.redis_host,
                port=self.settings.redis_port,
                db=self.settings.redis_db,
                password=self.settings.redis_password,
                ssl=self.settings.redis_ssl,
                max_connections=self.settings.redis_max_connections,
                socket_connect_timeout=self.settings.redis_timeout_seconds,
            )
            self.redis = Redis(connection_pool=pool, decode_responses=True)
            # Test connection
            await self.redis.ping()
            self.logger.info("Redis connection established")
        except Exception as e:
            self.logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self) -> None:
        """Close Redis connection"""
        if self.redis:
            await self.redis.aclose()
            self.logger.info("Redis connection closed")

    async def get_string(self, key: str) -> Optional[str]:
        """Get string value from cache"""
        if not self.redis:
            return None
        try:
            value = await self.redis.get(key)
            if value:
                self.logger.debug(f"Cache hit: {key}")
            return value
        except Exception as e:
            self.logger.error(f"Cache get error for key {key}: {e}")
            return None

    async def set_string(self, key: str, value: str, ttl_seconds: int) -> bool:
        """Set string value in cache with TTL"""
        if not self.redis:
            return False
        try:
            await self.redis.setex(key, ttl_seconds, value)
            self.logger.debug(f"Cache set: {key} (TTL: {ttl_seconds}s)")
            return True
        except Exception as e:
            self.logger.error(f"Cache set error for key {key}: {e}")
            return False

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Get JSON object from cache"""
        value = await self.get_string(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON decode error for key {key}: {e}")
                return None
        return None

    async def set_json(
        self, key: str, value: Dict[str, Any], ttl_seconds: int
    ) -> bool:
        """Set JSON object in cache with TTL"""
        try:
            json_str = json.dumps(value)
            return await self.set_string(key, json_str, ttl_seconds)
        except Exception as e:
            self.logger.error(f"JSON encode error for key {key}: {e}")
            return False

    async def get_jwks(self, issuer: str) -> Optional[Dict[str, Any]]:
        """Get cached JWKS for an issuer"""
        key = RedisKeyBuilder.jwks_key(issuer)
        return await self.get_json(key)

    async def set_jwks(
        self, issuer: str, jwks: Dict[str, Any]
    ) -> bool:
        """Cache JWKS for an issuer"""
        key = RedisKeyBuilder.jwks_key(issuer)
        return await self.set_json(key, jwks, self.settings.redis_jwks_ttl)

    async def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get cached tool schema"""
        key = RedisKeyBuilder.tool_schema_key(tool_name)
        return await self.get_json(key)

    async def set_tool_schema(self, tool_name: str, schema: Dict[str, Any]) -> bool:
        """Cache tool schema"""
        key = RedisKeyBuilder.tool_schema_key(tool_name)
        return await self.set_json(key, schema, self.settings.redis_tool_schema_ttl)

    async def get_tool_list(
        self, namespace: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Get cached tool list"""
        key = RedisKeyBuilder.tool_list_key(namespace)
        value = await self.get_string(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None

    async def set_tool_list(
        self, tools: List[Dict[str, Any]], namespace: Optional[str] = None
    ) -> bool:
        """Cache tool list"""
        key = RedisKeyBuilder.tool_list_key(namespace)
        try:
            json_str = json.dumps(tools)
            return await self.set_string(
                key, json_str, self.settings.redis_tool_schema_ttl
            )
        except Exception as e:
            self.logger.error(f"Error caching tool list: {e}")
            return False

    async def get_rls_policy(
        self, tenant_id: str, resource_type: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached RLS policy"""
        key = RedisKeyBuilder.rls_policy_key(tenant_id, resource_type)
        return await self.get_json(key)

    async def set_rls_policy(
        self, tenant_id: str, resource_type: str, policy: Dict[str, Any]
    ) -> bool:
        """Cache RLS policy"""
        key = RedisKeyBuilder.rls_policy_key(tenant_id, resource_type)
        return await self.set_json(key, policy, self.settings.redis_rls_policy_ttl)

    async def get_scope_mapping(
        self, tenant_id: str, connector_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached scope mapping"""
        key = RedisKeyBuilder.scope_mapping_key(tenant_id, connector_id)
        return await self.get_json(key)

    async def set_scope_mapping(
        self, tenant_id: str, connector_id: str, mapping: Dict[str, Any]
    ) -> bool:
        """Cache scope mapping"""
        key = RedisKeyBuilder.scope_mapping_key(tenant_id, connector_id)
        return await self.set_json(key, mapping, self.settings.redis_scope_mapping_ttl)

    async def delete(self, key: str) -> bool:
        """Delete a key from cache"""
        if not self.redis:
            return False
        try:
            await self.redis.delete(key)
            self.logger.debug(f"Cache key deleted: {key}")
            return True
        except Exception as e:
            self.logger.error(f"Error deleting cache key {key}: {e}")
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        if not self.redis:
            return 0
        try:
            keys = await self.redis.keys(pattern)
            if keys:
                count = await self.redis.delete(*keys)
                self.logger.debug(f"Deleted {count} cache keys matching {pattern}")
                return count
            return 0
        except Exception as e:
            self.logger.error(f"Error deleting cache keys with pattern {pattern}: {e}")
            return 0

    async def flush_all(self) -> bool:
        """Flush all cache (development only)"""
        if not self.redis:
            return False
        try:
            await self.redis.flushdb()
            self.logger.warning("Cache flushed (DEVELOPMENT ONLY)")
            return True
        except Exception as e:
            self.logger.error(f"Error flushing cache: {e}")
            return False

    async def health_check(self) -> bool:
        """Check Redis health"""
        if not self.redis:
            return False
        try:
            await self.redis.ping()
            return True
        except Exception as e:
            self.logger.error(f"Redis health check failed: {e}")
            return False

    async def get_stats(self) -> Dict[str, Any]:
        """Get Redis connection stats"""
        if not self.redis:
            return {}
        try:
            info = await self.redis.info()
            return {
                "connected_clients": info.get("connected_clients"),
                "used_memory_mb": info.get("used_memory", 0) / 1024 / 1024,
                "total_commands_processed": info.get("total_commands_processed"),
            }
        except Exception as e:
            self.logger.error(f"Error getting Redis stats: {e}")
            return {}


# Global cache instance
_cache_instance: Optional[RedisCache] = None


def get_cache() -> Optional[RedisCache]:
    """Get global cache instance"""
    return _cache_instance


async def initialize_cache(settings: Settings) -> RedisCache:
    """Initialize global cache instance"""
    global _cache_instance
    _cache_instance = RedisCache(settings)
    await _cache_instance.connect()
    return _cache_instance


async def cleanup_cache() -> None:
    """Cleanup global cache instance"""
    global _cache_instance
    if _cache_instance:
        await _cache_instance.disconnect()
        _cache_instance = None
