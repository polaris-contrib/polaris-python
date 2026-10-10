"""Local token-bucket and concurrency rate limiting."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import RLock
from typing import Iterable

from polarismesh_specification.api.v1.traffic_manage import ratelimit_pb2

from polaris_python.core.error import RateLimitExceededError


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    """Limits applied to one service key."""

    key: str
    max_qps: float | None = None
    burst: int | None = None
    max_concurrency: int | None = None
    enabled: bool = True


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float
    active: int = 0


class RateLimiter:
    """Apply local QPS and concurrency limits with no background task."""

    def __init__(self, rules: Iterable[RateLimitRule] = ()) -> None:
        self._rules: dict[str, RateLimitRule] = {rule.key: rule for rule in rules}
        self._buckets: dict[str, _Bucket] = {}
        self._lock = RLock()

    @property
    def rules(self) -> tuple[RateLimitRule, ...]:
        """Return configured rate limit rules."""
        return tuple(self._rules.values())

    def set_rules(self, rules: Iterable[RateLimitRule]) -> None:
        """Replace local rate limit rules."""
        with self._lock:
            self._rules = {rule.key: rule for rule in rules}
            self._buckets.clear()

    def try_acquire(self, key: str) -> bool:
        """Try to reserve one request slot without waiting."""
        with self._lock:
            rule = self._rules.get(key) or self._rules.get("*")
            if rule is None or not rule.enabled:
                return True
            now = time.monotonic()
            bucket = self._buckets.setdefault(
                key,
                _Bucket(
                    tokens=float(rule.burst or max(1, int(rule.max_qps or 1))),
                    updated_at=now,
                ),
            )
            if rule.max_qps:
                elapsed = max(0.0, now - bucket.updated_at)
                bucket.tokens = min(float(rule.burst or max(1, int(rule.max_qps))), bucket.tokens + elapsed * rule.max_qps)
                bucket.updated_at = now
                if bucket.tokens < 1:
                    return False
            if rule.max_concurrency is not None and bucket.active >= rule.max_concurrency:
                return False
            if rule.max_qps:
                bucket.tokens -= 1
            if rule.max_concurrency is not None:
                bucket.active += 1
            return True

    async def acquire(self, key: str) -> None:
        """Reserve a request slot or raise ``RateLimitExceededError``."""
        if not self.try_acquire(key):
            raise RateLimitExceededError(f"rate limit exceeded for {key}")

    def release(self, key: str) -> None:
        """Release a concurrency slot after a request completes."""
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is not None and bucket.active:
                bucket.active -= 1

    def update_from_proto(self, rate_limit: ratelimit_pb2.RateLimit) -> None:
        """Import QPS and concurrency rules from specification messages."""
        rules: list[RateLimitRule] = []
        for rule in rate_limit.rules:
            key = _service_key(rule.namespace.value, rule.service.value)
            if rule.resource == ratelimit_pb2.Rule.CONCURRENCY:
                max_concurrency = rule.concurrencyAmount.maxAmount
                rules.append(RateLimitRule(key, max_concurrency=max_concurrency, enabled=not rule.disable.value))
                continue
            for amount in rule.amounts:
                duration = amount.validDuration.seconds + amount.validDuration.nanos / 1_000_000_000
                if duration <= 0:
                    duration = 1.0
                max_qps = amount.maxAmount.value / duration
                rules.append(
                    RateLimitRule(
                        key,
                        max_qps=max_qps,
                        burst=max(1, amount.maxAmount.value),
                        enabled=not rule.disable.value,
                    )
                )
                break
        self.set_rules(rules)


def _service_key(namespace: str, service: str) -> str:
    """Build the stable local key used by governance plugins."""
    return f"{namespace}/{service}"

