"""Consumer-side service instance discovery APIs."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from polarismesh_specification.api.v1.service_manage import request_pb2, service_pb2

from polaris_python.api.context import SDKContext
from polaris_python.api.provider import _sync_or_coroutine
from polaris_python.core.error import CircuitOpenError, PolarisError
from polaris_python.core.instance import (
    PROTOCOL_METADATA,
    RESOURCE_TYPE_METADATA,
    VERSION_METADATA,
    ServiceInstance,
)

logger = logging.getLogger(__name__)
_DISCOVER_TYPES = (
    request_pb2.DiscoverRequest.INSTANCE,
    request_pb2.DiscoverRequest.ROUTING,
    request_pb2.DiscoverRequest.NEARBY_ROUTE_RULE,
    request_pb2.DiscoverRequest.RATE_LIMIT,
    request_pb2.DiscoverRequest.CIRCUIT_BREAKER,
)


class ConsumerAPI:
    """Discover cached Polaris service instances with local filtering."""

    def __init__(self, context: SDKContext) -> None:
        self._context = context

    def _check_available(self) -> None:
        if self._context.destroyed:
            raise PolarisError("SDKContext has been destroyed")

    async def async_get_all_instances(
        self,
        service: str,
        *,
        namespace: str | None = None,
        metadata: dict[str, str] | None = None,
        protocol: str | None = None,
        version: str | None = None,
        resource_type: str | None = None,
        include_isolated: bool = False,
        routing_metadata: Mapping[str, str] | None = None,
        method: str = "",
        headers: Mapping[str, str] | None = None,
        query: Mapping[str, str] | None = None,
        caller_ip: str = "",
    ) -> list[ServiceInstance]:
        """Discover all instances for a service and apply metadata filters.

        Served from the local cache. The first call waits for the server;
        when it is unavailable the last cached or persisted snapshot is used.
        """
        self._check_available()
        if not service.strip():
            raise ValueError("service must not be empty")
        effective_namespace = namespace if namespace is not None else self._context.config.namespace
        await self._context.ensure_resources(
            effective_namespace,
            service,
            _DISCOVER_TYPES,
            required=request_pb2.DiscoverRequest.INSTANCE,
        )
        instances = await self._context.registry.get_instances(effective_namespace, service)
        filtered = self._filter_instances(
            instances,
            metadata=metadata,
            protocol=protocol,
            version=version,
            resource_type=resource_type,
            include_isolated=include_isolated,
        )
        return self._context.router.route(
            filtered,
            context=self._routing_context(
                routing_metadata=routing_metadata,
                method=method,
                headers=headers,
                query=query,
                caller_ip=caller_ip,
            ),
        )

    def get_all_instances(self, service: str, **kwargs: Any) -> list[ServiceInstance] | Any:
        """Synchronously discover all instances, or return a coroutine in async code."""
        return _sync_or_coroutine(self.async_get_all_instances(service, **kwargs), context=self._context)

    async def async_get_healthy_instances(self, service: str, **kwargs: Any) -> list[ServiceInstance]:
        """Discover instances that are healthy and not isolated."""
        kwargs["include_isolated"] = False
        instances = await self.async_get_all_instances(service, **kwargs)
        return [instance for instance in instances if instance.healthy and not instance.isolate]

    def get_healthy_instances(self, service: str, **kwargs: Any) -> list[ServiceInstance] | Any:
        """Synchronously discover healthy instances, or return a coroutine in async code."""
        return _sync_or_coroutine(self.async_get_healthy_instances(service, **kwargs), context=self._context)

    async def async_get_one_instance(self, service: str, **kwargs: Any) -> ServiceInstance:
        """Return the first eligible instance from the local snapshot."""
        instances = await self.async_get_healthy_instances(service, **kwargs)
        if not instances:
            raise PolarisError(f"no healthy instance found for service {service}")
        available = [
            instance
            for instance in instances
            if not self._context.circuit_breaker.is_open(self._governance_key(instance))
        ]
        if not available:
            raise CircuitOpenError(f"all healthy instances are circuit-open for {service}")
        return self._context.load_balancer.choose(available, key=self._governance_key(available[0]))

    def get_one_instance(self, service: str, **kwargs: Any) -> ServiceInstance | Any:
        """Synchronously return one healthy instance, or return a coroutine in async code."""
        return _sync_or_coroutine(self.async_get_one_instance(service, **kwargs), context=self._context)

    async def async_update_service_call_result(
        self,
        instance: ServiceInstance,
        *,
        success: bool,
        latency_ms: float | None = None,
    ) -> None:
        """Accept call results for the future circuit-breaker plugin."""
        self._check_available()
        await self.async_after_call(instance, success=success)
        logger.debug("service call result service=%s instance=%s success=%s latency_ms=%s", instance.service, instance.id, success, latency_ms)

    def update_service_call_result(self, instance: ServiceInstance, **kwargs: Any) -> None | Any:
        """Synchronously record a call result, or return a coroutine in async code."""
        return _sync_or_coroutine(
            self.async_update_service_call_result(instance, **kwargs),
            context=self._context,
        )

    async def async_before_call(self, instance: ServiceInstance) -> None:
        """Reserve a rate-limit slot and check the instance circuit."""
        self._check_available()
        key = self._governance_key(instance)
        await self._context.rate_limiter.acquire(key)
        try:
            self._context.circuit_breaker.check(key)
        except Exception:
            self._context.rate_limiter.release(key)
            raise

    def before_call(self, instance: ServiceInstance) -> None | Any:
        """Synchronously run ``async_before_call`` or return its coroutine."""
        return _sync_or_coroutine(self.async_before_call(instance), context=self._context)

    async def async_after_call(self, instance: ServiceInstance, *, success: bool) -> None:
        """Release a concurrency slot and record the circuit outcome."""
        self._check_available()
        key = self._governance_key(instance)
        self._context.rate_limiter.release(key)
        self._context.circuit_breaker.record(key, success=success)

    def after_call(self, instance: ServiceInstance, *, success: bool) -> None | Any:
        """Synchronously run ``async_after_call`` or return its coroutine."""
        return _sync_or_coroutine(
            self.async_after_call(instance, success=success),
            context=self._context,
        )

    @staticmethod
    def _filter_instances(
        instances: list[service_pb2.Instance],
        *,
        metadata: dict[str, str] | None,
        protocol: str | None,
        version: str | None,
        resource_type: str | None,
        include_isolated: bool,
    ) -> list[ServiceInstance]:
        result: list[ServiceInstance] = []
        for proto in instances:
            item = ServiceInstance.from_proto(proto)
            if item.isolate and not include_isolated:
                continue
            if protocol and item.protocol != protocol and item.metadata.get(PROTOCOL_METADATA) != protocol:
                continue
            if version and item.version != version and item.metadata.get(VERSION_METADATA) != version:
                continue
            if resource_type and item.metadata.get(RESOURCE_TYPE_METADATA) != resource_type:
                continue
            if metadata and any(item.metadata.get(key) != value for key, value in metadata.items()):
                continue
            result.append(item)
        return result

    @staticmethod
    def _governance_key(instance: ServiceInstance) -> str:
        return f"{instance.namespace}/{instance.service}"

    @staticmethod
    def _routing_context(
        *,
        routing_metadata: Mapping[str, str] | None,
        method: str,
        headers: Mapping[str, str] | None,
        query: Mapping[str, str] | None,
        caller_ip: str,
    ) -> Any:
        from polaris_python.plugin.router import RoutingContext

        return RoutingContext(
            metadata=routing_metadata or {},
            method=method,
            headers=headers or {},
            query=query or {},
            caller_ip=caller_ip,
        )

