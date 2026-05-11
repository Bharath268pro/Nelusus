"""Utilities for caching and performance optimization"""

import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Manages Redis caching with TTL support.
    Target: < 50ms overhead for token validation
    """

    def __init__(self, redis_client=None, default_ttl: int = 3600):
        """
        Initialize cache manager.

        Args:
            redis_client: Redis client instance
            default_ttl: Default TTL in seconds
        """
        self.redis = redis_client
        self.default_ttl = default_ttl

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if not self.redis:
            return None
        try:
            value = await self.redis.get(key)
            return value
        except Exception as e:
            logger.error(f"Cache get error for key {key}: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache"""
        if not self.redis:
            return False
        try:
            ttl = ttl or self.default_ttl
            await self.redis.setex(key, ttl, value)
            return True
        except Exception as e:
            logger.error(f"Cache set error for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete value from cache"""
        if not self.redis:
            return False
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error for key {key}: {e}")
            return False

    async def clear_prefix(self, prefix: str) -> int:
        """Clear all keys matching a prefix"""
        if not self.redis:
            return 0
        try:
            cursor = "0"
            deleted = 0
            while True:
                cursor, keys = await self.redis.scan(
                    cursor, match=f"{prefix}*", count=100
                )
                if keys:
                    deleted += await self.redis.delete(*keys)
                if cursor == "0":
                    break
            return deleted
        except Exception as e:
            logger.error(f"Cache clear prefix error for {prefix}: {e}")
            return 0
