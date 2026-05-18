"""Phase 2D: Context Hydration Engine + Connector Health

ContextHydrationEngine – loads tenant context, connector health, and memory
ConnectorHealthRegistry – tracks per-connector reliability for confidence scoring
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.models.orchestration import (
    ConnectorContext,
    HydratedContext,
)

logger = logging.getLogger(__name__)

_HYDRATION_PREFIX = "nexusmcp:agent:context"
_MEMORY_PREFIX = "nexusmcp:agent:memory"
_CONNECTOR_HEALTH_PREFIX = "nexusmcp:agent:health"


class ConnectorHealthRegistry:
    """
    Tracks per-connector reliability metrics.
    Used by ConfidenceScoringEngine for connector_reliability dimension.

    Data stored in Redis:
    nexusmcp:agent:health:{namespace} → {latency_p99, error_rate, auth_valid}
    """

    KNOWN_NAMESPACES = [
        "salesforce", "shopify", "hubspot",
        "zendesk", "stripe", "internal",
    ]

    def __init__(self, cache=None):
        self._cache = cache
        # In-memory fallback baselines
        self._baselines: Dict[str, Dict[str, Any]] = {
            ns: {"latency_p99_ms": 150.0, "error_rate_pct": 2.0, "auth_valid": True}
            for ns in self.KNOWN_NAMESPACES
        }

    async def get(self, namespace: str) -> ConnectorContext:
        """Return ConnectorContext for a namespace."""
        data = await self._load(namespace)
        return ConnectorContext(
            namespace=namespace,
            available=data.get("auth_valid", True) and data.get("error_rate_pct", 0) < 50,
            latency_p99_ms=data.get("latency_p99_ms", 150.0),
            error_rate_pct=data.get("error_rate_pct", 2.0),
            auth_valid=data.get("auth_valid", True),
            rate_limit_remaining=data.get("rate_limit_remaining"),
            metadata=data.get("metadata", {}),
        )

    async def get_many(self, namespaces: List[str]) -> Dict[str, ConnectorContext]:
        """Batch load multiple connector contexts."""
        result = {}
        for ns in namespaces:
            result[ns] = await self.get(ns)
        return result

    async def reliability_score(self, namespace: str) -> float:
        """
        0.0 = completely unreliable, 1.0 = perfectly reliable.
        Formula: (1 - error_rate/100) * (1 if latency < 500ms else 0.7)
        """
        ctx = await self.get(namespace)
        if not ctx.available:
            return 0.10
        error_factor = 1.0 - min(ctx.error_rate_pct / 100.0, 1.0)
        latency_factor = 1.0 if ctx.latency_p99_ms < 500 else 0.70
        return round(error_factor * latency_factor, 4)

    async def record_call(
        self, namespace: str, success: bool, latency_ms: float
    ) -> None:
        """Update connector health metrics after a call."""
        if not self._cache or not self._cache.redis:
            return
        key = f"{_CONNECTOR_HEALTH_PREFIX}:{namespace}"
        try:
            raw = await self._cache.redis.get(key)
            data = json.loads(raw) if raw else self._baselines.get(namespace, {})

            # Exponential moving average
            alpha = 0.1
            old_latency = data.get("latency_p99_ms", latency_ms)
            data["latency_p99_ms"] = round(
                alpha * latency_ms + (1 - alpha) * old_latency, 2
            )
            old_err = data.get("error_rate_pct", 0.0)
            call_err = 0.0 if success else 100.0
            data["error_rate_pct"] = round(
                alpha * call_err + (1 - alpha) * old_err, 2
            )
            await self._cache.redis.setex(key, 3600, json.dumps(data))
        except Exception as e:
            logger.error(f"[ConnectorHealth] record_call error: {e}")

    async def _load(self, namespace: str) -> Dict[str, Any]:
        if self._cache and self._cache.redis:
            key = f"{_CONNECTOR_HEALTH_PREFIX}:{namespace}"
            try:
                raw = await self._cache.redis.get(key)
                if raw:
                    return json.loads(raw)
            except Exception as e:
                logger.error(f"[ConnectorHealth] load error: {e}")
        return self._baselines.get(namespace, {
            "latency_p99_ms": 200.0, "error_rate_pct": 5.0, "auth_valid": True
        })


class ContextHydrationEngine:
    """
    Loads and assembles HydratedContext for a reasoning session.

    Sources:
    1. Connector health (ConnectorHealthRegistry)
    2. Historical intents from Redis memory store
    3. Cached memory snippets (facts from prior executions)
    4. RLS context (from request.state)
    """

    MEMORY_TTL = 86400       # 24h
    CONTEXT_TTL = 3600       # 1h
    MAX_MEMORY_SNIPPETS = 10
    MAX_HISTORICAL_INTENTS = 5

    def __init__(
        self,
        health_registry: ConnectorHealthRegistry,
        cache=None,
    ):
        self._health = health_registry
        self._cache = cache

    async def hydrate(
        self,
        tenant_id: str,
        user_id: str,
        intent: str,
        required_connectors: List[str],
        rls_context: Optional[Dict[str, Any]] = None,
    ) -> HydratedContext:
        """
        Build a complete HydratedContext for a reasoning session.
        """
        t0 = time.monotonic()

        # 1. Connector health
        connector_contexts = await self._health.get_many(required_connectors)

        # 2. Historical intents
        historical = await self._load_historical_intents(tenant_id)

        # 3. Memory snippets
        memory = await self._load_memory_snippets(tenant_id, intent)

        ctx = HydratedContext(
            tenant_id=tenant_id,
            user_id=user_id,
            intent=intent,
            connector_contexts=connector_contexts,
            historical_intents=historical,
            memory_snippets=memory,
            rls_context=rls_context or {},
            hydration_latency_ms=round((time.monotonic() - t0) * 1000, 2),
        )

        # Persist context for downstream use
        await self._persist_context(ctx)

        # Record intent in history
        await self._record_intent(tenant_id, intent)

        logger.info(
            f"[Hydration] tenant={tenant_id}, connectors={list(connector_contexts.keys())}, "
            f"memory={len(memory)}, latency={ctx.hydration_latency_ms:.1f}ms"
        )
        return ctx

    async def store_memory(
        self,
        tenant_id: str,
        key: str,
        value: Any,
        ttl: int = MEMORY_TTL,
    ) -> None:
        """Store a fact in tenant memory for future context hydration."""
        if not self._cache or not self._cache.redis:
            return
        redis_key = f"{_MEMORY_PREFIX}:{tenant_id}:{key}"
        try:
            await self._cache.redis.setex(
                redis_key, ttl,
                json.dumps({"key": key, "value": value, "stored_at": datetime.utcnow().isoformat()})
            )
        except Exception as e:
            logger.error(f"[Hydration] store_memory error: {e}")

    async def load_context(self, session_id: str) -> Optional[HydratedContext]:
        """Load a previously persisted context by session_id."""
        if not self._cache or not self._cache.redis:
            return None
        key = f"{_HYDRATION_PREFIX}:{session_id}"
        try:
            raw = await self._cache.redis.get(key)
            if raw:
                return HydratedContext.model_validate_json(raw)
        except Exception as e:
            logger.error(f"[Hydration] load_context error: {e}")
        return None

    async def _persist_context(self, ctx: HydratedContext) -> None:
        if not self._cache or not self._cache.redis:
            return
        key = f"{_HYDRATION_PREFIX}:{ctx.session_id}"
        try:
            await self._cache.redis.setex(key, self.CONTEXT_TTL, ctx.model_dump_json())
        except Exception as e:
            logger.error(f"[Hydration] persist_context error: {e}")

    async def _load_historical_intents(self, tenant_id: str) -> List[str]:
        if not self._cache or not self._cache.redis:
            return []
        key = f"{_MEMORY_PREFIX}:{tenant_id}:intents"
        try:
            raw = await self._cache.redis.lrange(key, 0, self.MAX_HISTORICAL_INTENTS - 1)
            return [r.decode() if isinstance(r, bytes) else r for r in raw]
        except Exception:
            return []

    async def _record_intent(self, tenant_id: str, intent: str) -> None:
        if not self._cache or not self._cache.redis:
            return
        key = f"{_MEMORY_PREFIX}:{tenant_id}:intents"
        try:
            await self._cache.redis.lpush(key, intent)
            await self._cache.redis.ltrim(key, 0, self.MAX_HISTORICAL_INTENTS - 1)
            await self._cache.redis.expire(key, self.MEMORY_TTL)
        except Exception:
            pass

    async def _load_memory_snippets(
        self, tenant_id: str, intent: str
    ) -> List[Dict[str, Any]]:
        if not self._cache or not self._cache.redis:
            return []
        # Simplified: load all tenant memory keys (production: use vector search)
        pattern = f"{_MEMORY_PREFIX}:{tenant_id}:*"
        snippets = []
        try:
            cursor = 0
            while True:
                cursor, keys = await self._cache.redis.scan(
                    cursor, match=pattern, count=50
                )
                for key in keys[:self.MAX_MEMORY_SNIPPETS]:
                    raw = await self._cache.redis.get(key)
                    if raw:
                        try:
                            snippets.append(json.loads(raw))
                        except Exception:
                            pass
                if cursor == 0 or len(snippets) >= self.MAX_MEMORY_SNIPPETS:
                    break
        except Exception as e:
            logger.error(f"[Hydration] load_memory_snippets error: {e}")
        return snippets[:self.MAX_MEMORY_SNIPPETS]
