"""Async gRPC transport for the Polaris service management API."""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

import grpc
from google.protobuf.message import Message
from polarismesh_specification.api.v1.service_manage import (
    client_pb2,
    grpcapi_pb2_grpc,
    request_pb2,
    response_pb2,
    service_pb2,
)

from polaris_python.core.config import Config
from polaris_python.core.error import PolarisTransportError
from polaris_python.core.log import NETWORK_LOGGER
from polaris_python.plugin.connector import ServerConnector

logger = logging.getLogger(NETWORK_LOGGER)

# ``request-id`` prefixes from polaris-java ``GrpcUtil``; ReportClient reuses the heartbeat sequence.
_REQUEST_ID_PREFIX = {
    "RegisterInstance": "1",
    "DeregisterInstance": "2",
    "Heartbeat": "3",
    "ReportClient": "3",
    "Discover": "4",
}
_REQUEST_ID_SEEDS = {prefix: itertools.count(1) for prefix in set(_REQUEST_ID_PREFIX.values())}


def _request_id(method: str) -> tuple[tuple[str, str], ...]:
    prefix = _REQUEST_ID_PREFIX.get(method)
    if prefix is None:
        return ()
    return (("request-id", f"{prefix}{next(_REQUEST_ID_SEEDS[prefix])}"),)


class GrpcConnector(ServerConnector):
    """Connection manager with endpoint rotation and bounded RPC retries."""

    _RETRYABLE_STATUS = {
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
    }

    def __init__(self, config: Config) -> None:
        self.config = config
        self._addresses = list(config.server_addresses)
        self._channels: dict[str, grpc.aio.Channel] = {}
        self._stubs: dict[str, grpcapi_pb2_grpc.PolarisGRPCStub] = {}
        self._address_index = 0
        self._lock = asyncio.Lock()
        self._closed = False

    def _metadata(self) -> tuple[tuple[str, str], ...]:
        """Return the access-token header Polaris reads (``X-Polaris-Token``, as in Java and Go)."""
        if not self.config.token:
            return ()
        return (("x-polaris-token", self.config.token),)

    async def _stub(self, address: str) -> grpcapi_pb2_grpc.PolarisGRPCStub:
        async with self._lock:
            if self._closed:
                raise PolarisTransportError("gRPC connector has been closed")
            if address not in self._stubs:
                channel = grpc.aio.insecure_channel(address)
                self._channels[address] = channel
                self._stubs[address] = grpcapi_pb2_grpc.PolarisGRPCStub(channel)
            return self._stubs[address]

    async def _unary(
        self,
        method: str,
        request: Message,
        extra_metadata: tuple[tuple[str, str], ...] = (),
    ) -> response_pb2.Response:
        if not self._addresses:
            raise PolarisTransportError("no Polaris server address configured")
        last_error: Exception | None = None
        attempts = self.config.retry_attempts + 1
        for attempt in range(attempts):
            address = self._addresses[self._address_index % len(self._addresses)]
            try:
                stub = await self._stub(address)
                rpc: Callable[..., Awaitable[response_pb2.Response]] = getattr(stub, method)
                return await rpc(
                    request,
                    timeout=self.config.timeout_seconds,
                    metadata=_request_id(method) + extra_metadata + self._metadata(),
                )
            except grpc.aio.AioRpcError as exc:
                last_error = exc
                if exc.code() not in self._RETRYABLE_STATUS or attempt + 1 >= attempts:
                    break
                self._address_index = (self._address_index + 1) % len(self._addresses)
                logger.warning(
                    "Polaris %s on %s failed with %s; retrying on %s",
                    method,
                    address,
                    exc.code().name,
                    self._addresses[self._address_index],
                )
                await asyncio.sleep(self.config.retry_backoff_seconds * (2**attempt))
        raise PolarisTransportError(f"Polaris {method} failed: {last_error}") from last_error

    async def register_instance(self, instance: service_pb2.Instance) -> response_pb2.Response:
        """Call ``PolarisGRPC.RegisterInstance`` with the ``async-regis`` header Java sends."""
        return await self._unary("RegisterInstance", instance, (("async-regis", "true"),))

    async def deregister_instance(self, instance: service_pb2.Instance) -> response_pb2.Response:
        """Call ``PolarisGRPC.DeregisterInstance``."""
        return await self._unary("DeregisterInstance", instance)

    async def heartbeat(self, instance: service_pb2.Instance) -> response_pb2.Response:
        """Call ``PolarisGRPC.Heartbeat``."""
        return await self._unary("Heartbeat", instance)

    async def report_client(self, client: client_pb2.Client) -> response_pb2.Response:
        """Call ``PolarisGRPC.ReportClient``."""
        return await self._unary("ReportClient", client)

    async def _request_once(
        self, address: str, request: request_pb2.DiscoverRequest
    ) -> AsyncIterator[response_pb2.DiscoverResponse]:
        stub = await self._stub(address)
        pending = request_pb2.DiscoverRequest()
        pending.CopyFrom(request)

        # Polaris answers each DiscoverRequest once and never pushes changes,
        # so the request is resent with the last revision to pick up updates.
        async def requests() -> AsyncIterator[request_pb2.DiscoverRequest]:
            while True:
                outgoing = request_pb2.DiscoverRequest()
                outgoing.CopyFrom(pending)
                yield outgoing
                await asyncio.sleep(self.config.refresh_interval_seconds)

        stream = stub.Discover(requests(), timeout=None, metadata=_request_id("Discover") + self._metadata())
        async for response in stream:
            revision = response.service.revision.value
            if revision:
                pending.service.revision.value = revision
            yield response

    async def _discover(self, request: request_pb2.DiscoverRequest) -> AsyncIterator[response_pb2.DiscoverResponse]:
        """Reconnect a discovery stream after transient endpoint failures."""
        if not self._addresses:
            raise PolarisTransportError("no Polaris server address configured")
        resource = (
            f"{request_pb2.DiscoverRequest.DiscoverRequestType.Name(request.type)} "
            f"{request.service.namespace.value}/{request.service.name.value}"
        )
        failing = False
        while not self._closed:
            address = self._addresses[self._address_index % len(self._addresses)]
            try:
                yielded = False
                async for response in self._request_once(address, request):
                    yielded = True
                    if failing:
                        logger.info("Discover %s reconnected to %s", resource, address)
                        failing = False
                    yield response
                if self._closed:
                    return
                await asyncio.sleep(
                    self.config.retry_backoff_seconds if yielded else max(self.config.retry_backoff_seconds, 0.05)
                )
            except grpc.aio.AioRpcError as exc:
                if exc.code() not in self._RETRYABLE_STATUS:
                    raise PolarisTransportError(f"Polaris Discover failed: {exc}") from exc
                if not failing:
                    logger.warning("Discover %s on %s failed with %s; reconnecting", resource, address, exc.code().name)
                    failing = True
                self._address_index = (self._address_index + 1) % len(self._addresses)
                await asyncio.sleep(self.config.retry_backoff_seconds)

    def discover(self, request: request_pb2.DiscoverRequest) -> AsyncIterator[response_pb2.DiscoverResponse]:
        """Open a reconnecting ``PolarisGRPC.Discover`` stream."""
        return self._discover(request)

    async def close(self) -> None:
        """Close all gRPC channels."""
        self._closed = True
        channels = list(self._channels.values())
        self._channels.clear()
        self._stubs.clear()
        for channel in channels:
            await channel.close()
