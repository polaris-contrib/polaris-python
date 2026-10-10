"""Public service-side rate-limit API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from polaris_python.api.consumer import ConsumerAPI
from polaris_python.api.context import SDKContext
from polaris_python.api.provider import _sync_or_coroutine


@dataclass(frozen=True, slots=True)
class QuotaRequest:
    """A quota request matching the Java/Go LimitAPI shape."""

    service: str
    namespace: str = ""
    method: str = ""
    labels: Mapping[str, str] = field(default_factory=dict)
    count: int = 1


@dataclass(slots=True)
class QuotaResponse:
    """The result of one quota acquisition."""

    allowed: bool
    info: str = ""
    wait_ms: int = 0
    _release: Any = field(default=None, repr=False)
    _released: bool = field(default=False, init=False, repr=False)

    def release(self) -> None:
        """Release a concurrency reservation, if one was acquired."""
        if not self._released and self._release is not None:
            self._release()
            self._released = True


class LimitAPI:
    """Acquire quotas using rules delivered by Polaris ``Discover``."""

    def __init__(self, context: SDKContext) -> None:
        self._context = context
        self._consumer = ConsumerAPI(context)

    async def async_get_quota(self, request: QuotaRequest) -> QuotaResponse:
        """Load the service rule stream and acquire one local quota."""
        if not request.service.strip():
            raise ValueError("service must not be empty")
        if request.count <= 0:
            raise ValueError("count must be greater than zero")
        namespace = request.namespace or self._context.config.namespace
        await self._consumer.async_get_all_instances(request.service, namespace=namespace)
        key = f"{namespace}/{request.service}"
        acquired = 0
        for _ in range(request.count):
            if not self._context.rate_limiter.try_acquire(key):
                for _ in range(acquired):
                    self._context.rate_limiter.release(key)
                return QuotaResponse(False, info=f"rate limit exceeded for {key}")
            acquired += 1

        def release() -> None:
            for _ in range(acquired):
                self._context.rate_limiter.release(key)

        return QuotaResponse(True, _release=release)

    def get_quota(self, request: QuotaRequest) -> QuotaResponse | Any:
        """Synchronously acquire a quota, or return a coroutine in async code."""
        return _sync_or_coroutine(self.async_get_quota(request), context=self._context)

