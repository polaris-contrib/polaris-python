"""SDK runtime and lifecycle management."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Coroutine, TypeVar

from polarismesh_specification.api.v1.service_manage import request_pb2, response_pb2, service_pb2

from polaris_python.api.register import RegisterFlow
from polaris_python.api.report import ClientReporter
from polaris_python.core.config import Config
from polaris_python.core.error import (
    DATA_NO_CHANGE,
    NO_NEED_UPDATE,
    NOT_FOUND_RESOURCE,
    NOT_FOUND_SERVICE,
    PolarisError,
    PolarisTransportError,
    ensure_success,
    response_code,
)
from polaris_python.core.log import UPDATE_EVENT_LOGGER, configure_logging
from polaris_python.plugin.connector import ServerConnector
from polaris_python.plugin.grpc import GrpcConnector
from polaris_python.plugin.circuitbreaker import CircuitBreaker
from polaris_python.plugin.loadbalancer import WeightedLoadBalancer
from polaris_python.plugin.registry import CachedResource, InMemoryRegistry, LocalRegistry, PersistentRegistry
from polaris_python.plugin.ratelimiter import RateLimiter
from polaris_python.plugin.router import MetadataRouter

logger = logging.getLogger(__name__)
update_log = logging.getLogger(UPDATE_EVENT_LOGGER)
_SyncResult = TypeVar("_SyncResult")
_INSTANCE = response_pb2.DiscoverResponse.INSTANCE
_TYPE_NAME = response_pb2.DiscoverResponse.DiscoverResponseType


def discover_request(namespace: str, service: str, discover_type: int) -> request_pb2.DiscoverRequest:
    """Build the ``Discover`` request for one namespace/service/resource type."""
    return request_pb2.DiscoverRequest(
        type=discover_type,
        service=service_pb2.Service(name={"value": service}, namespace={"value": namespace}),
        Filter={"OnlyHealthyInstance": False},
    )


def _log_update(
    namespace: str,
    service: str,
    discover_type: int,
    previous: CachedResource | None,
    current: CachedResource,
    *,
    source: str,
) -> None:
    """Record one snapshot change on the update-event channel."""
    response = current.response
    if discover_type == _INSTANCE:
        size = f"instances={len(response.instances)}"
    elif discover_type == response_pb2.DiscoverResponse.ROUTING:
        routing = response.routing
        size = f"rules={len(routing.inbounds) + len(routing.outbounds) + len(routing.rules)}"
    elif discover_type == response_pb2.DiscoverResponse.NEARBY_ROUTE_RULE:
        size = f"rules={len(response.nearbyRouteRules)}"
    elif discover_type == response_pb2.DiscoverResponse.RATE_LIMIT:
        size = f"rules={len(response.rateLimit.rules)}"
    elif discover_type == response_pb2.DiscoverResponse.CIRCUIT_BREAKER:
        size = f"rules={len(response.circuitBreaker.rules)}"
    else:
        size = ""
    update_log.info(
        "%s %s/%s revision %r -> %r %s source=%s",
        _TYPE_NAME.Name(discover_type),
        namespace,
        service,
        previous.revision if previous else None,
        current.revision,
        size,
        source,
    )


@dataclass(slots=True)
class _Watch:
    """Background ``Discover`` stream for one namespace/service/type."""

    discover_type: int
    task: asyncio.Task[None] | None = None
    responded: asyncio.Event = field(default_factory=asyncio.Event)
    waited: bool = False
    restored: bool = False
    error: BaseException | None = None


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
        configure_logging(self.config)
        self.connector = connector or GrpcConnector(self.config)
        self.register_flow = RegisterFlow(self.config, self.connector)
        self.client_reporter = ClientReporter(self.config, self.connector)
        if registry is not None:
            self.registry = registry
        elif self.config.resolved_persist_dir is not None:
            self.registry = PersistentRegistry(
                self.config.resolved_persist_dir,
                max_write_retry=self.config.persist_max_write_retry,
                max_read_retry=self.config.persist_max_read_retry,
                retry_interval_seconds=self.config.persist_retry_interval_seconds,
            )
        else:
            self.registry = InMemoryRegistry()
        self.router = router or MetadataRouter()
        self.load_balancer = load_balancer or WeightedLoadBalancer()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self._destroyed = False
        self._resources_closed = False
        self._watches: dict[tuple[str, str, int], _Watch] = {}
        self._watch_streams: set[AsyncIterator[response_pb2.DiscoverResponse]] = set()
        self._discover_errors: dict[tuple[str, str, int], int] = {}
        self._last_access: dict[tuple[str, str], float] = {}
        self._expire_task: asyncio.Task[None] | None = None
        self._sync_loop: asyncio.AbstractEventLoop | None = None
        self._sync_thread: threading.Thread | None = None
        self._sync_loop_ready: threading.Event | None = None
        self._sync_start_lock = threading.Lock()
        logger.info(
            "Polaris SDK context created: client_id=%s servers=%s namespace=%r registry=%s persist_dir=%s "
            "refresh=%ss timeout=%ss service_expire=%s report=%s",
            self.client_reporter.client_id,
            self.config.server_addresses,
            self.config.namespace,
            type(self.registry).__name__,
            getattr(self.registry, "persist_dir", None),
            self.config.refresh_interval_seconds,
            self.config.timeout_seconds,
            f"{self.config.service_expire_seconds:g}s" if self.config.service_expire_enable else "off",
            "on" if self.config.report_enable else "off",
        )
        self.client_reporter.start()

    @property
    def destroyed(self) -> bool:
        return self._destroyed

    async def ensure_resources(
        self,
        namespace: str,
        service: str,
        discover_types: Sequence[int],
        *,
        required: int | None = None,
    ) -> None:
        """Watch resources, wait for their first snapshots, and degrade to cached data.

        A resource is waited on, for up to ``timeout_seconds`` and concurrently
        with the others, until the server answers once. When it does not, the
        last in-memory snapshot is served; without one, the persisted snapshot
        is restored. After one timed-out wait a resource is not waited on again
        while its stream keeps retrying in the background, except the
        ``required`` type while it still has no snapshot.

        ``required`` raises ``PolarisTransportError`` when that type has no
        snapshot at all and the server never answered. Each call counts as a
        read of the service for cache expiry.
        """
        self._check_available()
        self.client_reporter.start()
        self._last_access[(namespace, service)] = time.monotonic()
        self._start_expiry()
        watches = [self._watch(namespace, service, int(discover_type)) for discover_type in discover_types]
        pending: list[_Watch] = []
        for watch in watches:
            if watch.responded.is_set():
                continue
            if watch.waited and (
                watch.discover_type != required
                or await self.registry.get_resource(namespace, service, watch.discover_type) is not None
            ):
                continue
            pending.append(watch)
        if pending:
            waiters = [asyncio.ensure_future(watch.responded.wait()) for watch in pending]
            _, unfinished = await asyncio.wait(waiters, timeout=self.config.timeout_seconds)
            for waiter in unfinished:
                waiter.cancel()
            for watch in pending:
                watch.waited = True
        restored = [watch.discover_type for watch in watches if await self._degrade(namespace, service, watch)]
        if restored:
            logger.warning(
                "no Polaris snapshot for %s/%s yet; using persisted snapshots for %s",
                namespace,
                service,
                ", ".join(_TYPE_NAME.Name(discover_type) for discover_type in restored),
            )
        if required is None:
            return
        watch = next(item for item in watches if item.discover_type == int(required))
        if await self.registry.get_resource(namespace, service, watch.discover_type) is not None:
            return
        if not watch.responded.is_set() or watch.error is not None:
            raise PolarisTransportError(
                f"no Polaris snapshot for {namespace}/{service} within {self.config.timeout_seconds}s "
                "and no cached copy"
            ) from watch.error

    def _watch(self, namespace: str, service: str, discover_type: int) -> _Watch:
        """Return the live watch for one resource, starting a stream when needed."""
        key = (namespace, service, discover_type)
        previous = self._watches.get(key)
        if previous is not None and previous.task is not None and not previous.task.done():
            return previous
        watch = _Watch(
            discover_type,
            waited=previous.waited if previous else False,
            restored=previous.restored if previous else False,
        )
        stream = self.connector.discover(discover_request(namespace, service, discover_type))
        self._watch_streams.add(stream)
        watch.task = asyncio.create_task(
            self._consume_discovery(namespace, service, watch, stream),
            name=f"polaris-discover-{namespace}-{service}-{discover_type}",
        )
        self._watches[key] = watch
        return watch

    async def _consume_discovery(
        self,
        namespace: str,
        service: str,
        watch: _Watch,
        stream: AsyncIterator[response_pb2.DiscoverResponse],
    ) -> None:
        try:
            async for response in stream:
                try:
                    await self._apply_discover_response(namespace, service, watch.discover_type, response)
                except Exception:
                    logger.exception("could not apply Polaris discovery response for %s/%s", namespace, service)
                watch.error = None
                watch.responded.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            watch.error = exc
            logger.warning("Polaris discovery stream for %s/%s stopped: %s", namespace, service, exc)
        finally:
            watch.responded.set()
            self._watch_streams.discard(stream)
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()

    async def _degrade(self, namespace: str, service: str, watch: _Watch) -> bool:
        """Restore the persisted snapshot once when no snapshot is cached."""
        if watch.restored or await self.registry.get_resource(namespace, service, watch.discover_type) is not None:
            return False
        watch.restored = True
        resource = await self.registry.restore_resource(namespace, service, watch.discover_type)
        if resource is None:
            return False
        _log_update(namespace, service, watch.discover_type, None, resource, source="file")
        self._apply_rules(namespace, service, watch.discover_type, resource.response)
        return True

    async def _apply_discover_response(
        self,
        namespace: str,
        service: str,
        discover_type: int,
        response: response_pb2.DiscoverResponse,
    ) -> None:
        """Cache a server snapshot and apply its rules when it changed."""
        error_key = (namespace, service, discover_type)
        code = response_code(response)
        try:
            ensure_success(response)
        except PolarisError:
            # Discovery is polled every refresh interval; report each error code once.
            if self._discover_errors.get(error_key) != code:
                logger.warning("Polaris discovery returned code %s for %s/%s", code, namespace, service)
            self._discover_errors[error_key] = code
            if code in {NOT_FOUND_SERVICE, NOT_FOUND_RESOURCE}:
                cached = await self.registry.get_resource(namespace, service, discover_type)
                await self.registry.remove_resource(namespace, service, discover_type)
                if cached is not None:
                    update_log.info(
                        "%s %s/%s removed: service not found", _TYPE_NAME.Name(discover_type), namespace, service
                    )
            return
        self._discover_errors.pop(error_key, None)
        if code in {DATA_NO_CHANGE, NO_NEED_UPDATE}:
            return
        if discover_type == _INSTANCE and await self._protects_from_empty_push(namespace, service, response):
            return
        previous = await self.registry.get_resource(namespace, service, discover_type)
        if await self.registry.put_resource(namespace, service, discover_type, response):
            current = await self.registry.get_resource(namespace, service, discover_type)
            if current is not None:
                _log_update(namespace, service, discover_type, previous, current, source="server")
            self._apply_rules(namespace, service, discover_type, response)

    async def _protects_from_empty_push(
        self, namespace: str, service: str, response: response_pb2.DiscoverResponse
    ) -> bool:
        """Keep cached instances when zero protection is on and the server returns none."""
        if not self.config.zero_protection or len(response.instances) > 0:
            return False
        cached = await self.registry.get_resource(namespace, service, _INSTANCE)
        if cached is None or len(cached.response.instances) == 0:
            return False
        logger.warning(
            "Polaris returned no instances for %s/%s; zero protection keeps %d cached instances",
            namespace,
            service,
            len(cached.response.instances),
        )
        return True

    def _apply_rules(
        self, namespace: str, service: str, discover_type: int, response: response_pb2.DiscoverResponse
    ) -> None:
        """Push a rule snapshot into the routing and governance plugins."""
        if discover_type == response_pb2.DiscoverResponse.ROUTING and response.HasField("routing"):
            self.router.update_from_proto(response.routing)
        elif discover_type == response_pb2.DiscoverResponse.NEARBY_ROUTE_RULE:
            self.router.update_nearby_rules(namespace, service, response.nearbyRouteRules)
        elif discover_type == response_pb2.DiscoverResponse.RATE_LIMIT and response.HasField("rateLimit"):
            self.rate_limiter.update_from_proto(response.rateLimit)
        elif discover_type == response_pb2.DiscoverResponse.CIRCUIT_BREAKER and response.HasField("circuitBreaker"):
            self.circuit_breaker.update_from_proto(response.circuitBreaker)

    def _start_expiry(self) -> None:
        if not self.config.service_expire_enable:
            return
        if self._expire_task is None or self._expire_task.done():
            self._expire_task = asyncio.create_task(self._expire_loop(), name="polaris-cache-expire")

    async def _expire_loop(self) -> None:
        """Scan every ``service_expire_seconds``, like polaris-java ``InMemoryRegistry.ExpireTask``."""
        while True:
            await asyncio.sleep(self.config.service_expire_seconds)
            try:
                await self._expire_idle_services()
            except Exception:
                logger.exception("Polaris cache expiry scan failed")

    async def _expire_idle_services(self) -> None:
        """Remove services not read for ``service_expire_seconds`` from memory and disk.

        Their discovery streams stop; the next read discovers them again.
        """
        now = time.monotonic()
        idle = [
            (key, now - last)
            for key, last in list(self._last_access.items())
            if now - last >= self.config.service_expire_seconds
        ]
        for (namespace, service), idle_seconds in idle:
            await self._evict(namespace, service, idle_seconds)

    async def _evict(self, namespace: str, service: str, idle_seconds: float) -> None:
        self._last_access.pop((namespace, service), None)
        keys = [key for key in self._watches if key[:2] == (namespace, service)]
        watches = [self._watches.pop(key) for key in keys]
        tasks = [watch.task for watch in watches if watch.task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for key in keys:
            self._discover_errors.pop(key, None)
            await self.registry.remove_resource(*key)
        self.router.update_nearby_rules(namespace, service, ())
        update_log.info(
            "%s/%s expired after %.0fs without reads; removed %s",
            namespace,
            service,
            idle_seconds,
            ", ".join(_TYPE_NAME.Name(key[2]) for key in keys) or "nothing",
        )

    async def async_destroy(self) -> None:
        """Stop heartbeat, report, discovery and expiry tasks, then close connector and cache resources."""
        if self._resources_closed:
            return
        self._destroyed = True
        await self.register_flow.close()
        await self.client_reporter.close()
        if self._expire_task is not None:
            self._expire_task.cancel()
            if self._expire_task.get_loop() is asyncio.get_running_loop():
                await asyncio.gather(self._expire_task, return_exceptions=True)
            self._expire_task = None
        watchers = [watch.task for watch in self._watches.values() if watch.task is not None]
        self._watches.clear()
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
        logger.info("Polaris SDK context destroyed")

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
