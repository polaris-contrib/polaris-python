"""SDK runtime and lifecycle management."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from concurrent.futures import Future
from typing import Any, Coroutine, TypeVar

from polarismesh_specification.api.v1.service_manage import request_pb2, response_pb2

from polaris_python.core.config import Config
from polaris_python.core.error import PolarisError, ensure_success, response_code
from polaris_python.plugin.connector import ServerConnector
from polaris_python.plugin.grpc import GrpcConnector
from polaris_python.plugin.circuitbreaker import CircuitBreaker
from polaris_python.plugin.loadbalancer import WeightedLoadBalancer
from polaris_python.plugin.registry import JsonFileRegistry, LocalRegistry, InMemoryRegistry
from polaris_python.plugin.ratelimiter import RateLimiter
from polaris_python.plugin.router import MetadataRouter

logger = logging.getLogger(__name__)
_SyncResult = TypeVar("_SyncResult")


class SDKContext:
    """Process-wide runtime. Holds config and, later, the plugin engine.

    Mirrors polaris-java ``SDKContext``. Callers keep one instance and pass it
    to ``ProviderAPI``, ``ConsumerAPI``, and ``SkillAPI``.
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        connector: ServerConnector | None = None,
        registry: LocalRegistry | None = None,
        router: MetadataRouter | None = None,
        load_balancer: WeightedLoadBalancer | None = None,
        rate_limiter: RateLimiter | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.config = config or Config()
        self.connector = connector or GrpcConnector(self.config)
        if registry is not None:
            self.registry = registry
        elif self.config.resolved_cache_file is not None:
            self.registry = JsonFileRegistry(self.config.resolved_cache_file)
        else:
            self.registry = InMemoryRegistry()
        self.router = router or MetadataRouter()
        self.load_balancer = load_balancer or WeightedLoadBalancer()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self._destroyed = False
        self._resources_closed = False
        self._watchers: dict[tuple[str, str, int], asyncio.Task[None]] = {}
        self._watch_streams: set[AsyncIterator[response_pb2.DiscoverResponse]] = set()
        self._sync_loop: asyncio.AbstractEventLoop | None = None
        self._sync_thread: threading.Thread | None = None
        self._sync_loop_ready: threading.Event | None = None
        self._sync_start_lock = threading.Lock()

    @property
    def destroyed(self) -> bool:
        return self._destroyed

    async def ensure_discovery(
        self,
        namespace: str,
        service: str,
        request: request_pb2.DiscoverRequest,
        *,
        wait_for_initial: bool,
    ) -> None:
        """Start one discovery watcher and optionally wait for its first snapshot."""
        self._check_available()
        key = (namespace, service, int(request.type))
        watcher = self._watchers.get(key)
        if watcher is not None and not watcher.done():
            return
        stream = self.connector.discover(request)
        self._watch_streams.add(stream)
        cached = await self.registry.get_instances(namespace, service)
        if wait_for_initial and not cached:
            try:
                response = await asyncio.wait_for(
                    anext(stream), timeout=self.config.timeout_seconds
                )
                await self._apply_discover_response(namespace, service, response)
            except StopAsyncIteration:
                close = getattr(stream, "aclose", None)
                if close is not None:
                    await close()
                self._watch_streams.discard(stream)
                return
            except Exception:
                close = getattr(stream, "aclose", None)
                if close is not None:
                    await close()
                self._watch_streams.discard(stream)
                raise
        self._watchers[key] = asyncio.create_task(
            self._consume_discovery(namespace, service, stream),
            name=f"polaris-discover-{namespace}-{service}-{request.type}",
        )

    async def _consume_discovery(
        self,
        namespace: str,
        service: str,
        stream: AsyncIterator[response_pb2.DiscoverResponse],
    ) -> None:
        try:
            async for response in stream:
                await self._apply_discover_response(namespace, service, response)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Polaris discovery watcher stopped for %s/%s", namespace, service)
        finally:
            self._watch_streams.discard(stream)
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()

    async def _apply_discover_response(
        self, namespace: str, service: str, response: response_pb2.DiscoverResponse
    ) -> None:
        """Apply an instance snapshot while preserving the last good cache."""
        try:
            ensure_success(response)
        except PolarisError:
            logger.warning("Polaris discovery returned an error for %s/%s", namespace, service)
            return
        if response_code(response) in {200001, 200002}:
            return
        if response.type == response_pb2.DiscoverResponse.ROUTING and response.HasField("routing"):
            self.router.update_from_proto(response.routing)
            return
        if response.type == response_pb2.DiscoverResponse.RATE_LIMIT and response.HasField("rateLimit"):
            self.rate_limiter.update_from_proto(response.rateLimit)
            return
        if response.type == response_pb2.DiscoverResponse.CIRCUIT_BREAKER and response.HasField("circuitBreaker"):
            self.circuit_breaker.update_from_proto(response.circuitBreaker)
            return
        if response.type != response_pb2.DiscoverResponse.INSTANCE:
            return
        await self.registry.put_instances(namespace, service, response.instances)

    async def async_destroy(self) -> None:
        """Cancel discovery tasks and close connector and cache resources."""
        if self._resources_closed:
            return
        self._destroyed = True
        watchers = list(self._watchers.values())
        self._watchers.clear()
        for watcher in watchers:
            watcher.cancel()
        if watchers:
            await asyncio.gather(*watchers, return_exceptions=True)
        for stream in list(self._watch_streams):
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        self._watch_streams.clear()
        await self.connector.close()
        await self.registry.close()
        self._resources_closed = True

    def run_sync(self, coroutine: Coroutine[Any, Any, _SyncResult]) -> _SyncResult:
        """Run one SDK coroutine on the context's persistent sync event loop."""
        loop = self._ensure_sync_loop()
        if threading.current_thread() is self._sync_thread:
            raise RuntimeError("sync SDK APIs cannot be called from the sync event-loop thread")
        future: Future[_SyncResult] = asyncio.run_coroutine_threadsafe(coroutine, loop)
        return future.result()

    def _ensure_sync_loop(self) -> asyncio.AbstractEventLoop:
        with self._sync_start_lock:
            if self._sync_loop is not None and self._sync_loop.is_running():
                return self._sync_loop
            ready = threading.Event()
            self._sync_loop_ready = ready

            def run_loop() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._sync_loop = loop
                ready.set()
                loop.run_forever()
                loop.close()

            self._sync_thread = threading.Thread(
                target=run_loop,
                name="polaris-sdk-sync-loop",
                daemon=True,
            )
            self._sync_thread.start()
            ready.wait()
            if self._sync_loop is None:
                raise RuntimeError("failed to start the SDK sync event loop")
            return self._sync_loop

    def _stop_sync_loop(self) -> None:
        loop = self._sync_loop
        thread = self._sync_thread
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.config.timeout_seconds))
        self._sync_loop = None
        self._sync_thread = None
        self._sync_loop_ready = None

    def destroy(self) -> None:
        """Destroy the context; schedule cleanup when called in an event loop."""
        if self._destroyed and self._resources_closed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            if self._sync_loop is not None and self._sync_loop.is_running():
                self.run_sync(self.async_destroy())
                self._stop_sync_loop()
            else:
                asyncio.run(self.async_destroy())
        else:
            self._destroyed = True
            loop.create_task(self.async_destroy())

    def _check_available(self) -> None:
        if self._destroyed:
            raise PolarisError("SDKContext has been destroyed")
