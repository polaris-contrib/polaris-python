"""Provider registration, deregistration and heartbeat APIs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping

from google.protobuf.message import Message
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

from polaris_python.api.context import SDKContext
from polaris_python.api.register import describe as _describe
from polaris_python.api.register import prepare_heartbeat
from polaris_python.core.error import PolarisError, ensure_success
from polaris_python.core.instance import ServiceInstance, coerce_instance
from polaris_python.core.log import HEARTBEAT_LOGGER

logger = logging.getLogger(__name__)
heartbeat_log = logging.getLogger(HEARTBEAT_LOGGER)


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
        self._context.client_reporter.start()

    async def async_register_instance(
        self,
        instance: ServiceInstance | service_pb2.Instance | Mapping[str, Any],
    ) -> ServiceInstance:
        """Register an instance and keep it alive with a heartbeat every TTL.

        Like polaris-java ``registerInstance``: the TTL defaults to 5 seconds,
        and the heartbeat task re-registers the instance when Polaris reports
        it missing. Instances with health checks disabled get no heartbeat.
        """
        self._check_available()
        request = coerce_instance(instance, self._context.config.namespace)
        ttl = prepare_heartbeat(request)
        try:
            response = await self._context.connector.register_instance(request)
            self._ensure_response(response)
        except Exception as exc:
            logger.error("register %s failed: %s", _describe(request), exc)
            raise
        registered = request
        if isinstance(response, response_pb2.Response) and response.HasField("instance"):
            registered = response.instance
        logger.info("registered %s id=%s", _describe(request), registered.id.value)
        if ttl is not None:
            self._context.register_flow.track(request, registered.id.value or request.id.value, ttl)
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
        """Stop the instance's heartbeat and deregister it through ``PolarisGRPC.DeregisterInstance``."""
        self._check_available()
        request = coerce_instance(instance, self._context.config.namespace)
        await self._context.register_flow.untrack(request)
        try:
            response = await self._context.connector.deregister_instance(request)
            self._ensure_response(response)
        except Exception as exc:
            logger.error("deregister %s failed: %s", _describe(request), exc)
            raise
        logger.info("deregistered %s", _describe(request))

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
        """Send one heartbeat now; registered instances already heartbeat every TTL."""
        self._check_available()
        request = coerce_instance(instance, self._context.config.namespace)
        try:
            response = await self._context.connector.heartbeat(request)
            self._ensure_response(response)
        except Exception as exc:
            heartbeat_log.warning("heartbeat %s failed: %s", _describe(request), exc)
            raise
        heartbeat_log.info("heartbeat %s ok", _describe(request))

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
