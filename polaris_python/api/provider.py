"""Provider registration, deregistration and heartbeat APIs."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

from google.protobuf.message import Message
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

from polaris_python.api.context import SDKContext
from polaris_python.core.error import PolarisError, ensure_success
from polaris_python.core.instance import ServiceInstance, coerce_instance


def _sync_or_coroutine(coroutine: Any, *, context: SDKContext | None = None) -> Any:
    """Run an async implementation synchronously unless already in an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        if context is not None:
            return context.run_sync(coroutine)
        return asyncio.run(coroutine)
    return coroutine


class ProviderAPI:
    """Register and maintain a Polaris service instance."""

    def __init__(self, context: SDKContext) -> None:
        self._context = context

    def _check_available(self) -> None:
        if self._context.destroyed:
            raise PolarisError("SDKContext has been destroyed")

    async def async_register_instance(
        self,
        instance: ServiceInstance | service_pb2.Instance | Mapping[str, Any],
    ) -> ServiceInstance:
        """Register an instance through ``PolarisGRPC.RegisterInstance``."""
        self._check_available()
        request = coerce_instance(instance, self._context.config.namespace)
        response = await self._context.connector.register_instance(request)
        self._ensure_response(response)
        registered = request
        if isinstance(response, response_pb2.Response) and response.HasField("instance"):
            registered = response.instance
        return ServiceInstance.from_proto(registered)

    def register_instance(
        self,
        instance: ServiceInstance | service_pb2.Instance | Mapping[str, Any],
    ) -> ServiceInstance | Any:
        """Synchronously register an instance, or return a coroutine in async code."""
        return _sync_or_coroutine(self.async_register_instance(instance), context=self._context)

    async def async_deregister_instance(
        self,
        instance: ServiceInstance | service_pb2.Instance | Mapping[str, Any],
    ) -> None:
        """Deregister an instance through ``PolarisGRPC.DeregisterInstance``."""
        self._check_available()
        request = coerce_instance(instance, self._context.config.namespace)
        response = await self._context.connector.deregister_instance(request)
        self._ensure_response(response)

    def deregister_instance(
        self,
        instance: ServiceInstance | service_pb2.Instance | Mapping[str, Any],
    ) -> None | Any:
        """Synchronously deregister an instance, or return a coroutine in async code."""
        return _sync_or_coroutine(self.async_deregister_instance(instance), context=self._context)

    def deregister(
        self,
        instance: ServiceInstance | service_pb2.Instance | Mapping[str, Any],
    ) -> None | Any:
        """Compatibility alias for ``deregister_instance``."""
        return self.deregister_instance(instance)

    async def async_heartbeat(
        self,
        instance: ServiceInstance | service_pb2.Instance | Mapping[str, Any],
    ) -> None:
        """Send a heartbeat through ``PolarisGRPC.Heartbeat``."""
        self._check_available()
        request = coerce_instance(instance, self._context.config.namespace)
        response = await self._context.connector.heartbeat(request)
        self._ensure_response(response)

    def heartbeat(
        self,
        instance: ServiceInstance | service_pb2.Instance | Mapping[str, Any],
    ) -> None | Any:
        """Synchronously send a heartbeat, or return a coroutine in async code."""
        return _sync_or_coroutine(self.async_heartbeat(instance), context=self._context)

    @staticmethod
    def _ensure_response(response: Any) -> None:
        if isinstance(response, Message):
            ensure_success(response)
