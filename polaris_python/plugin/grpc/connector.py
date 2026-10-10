"""Async gRPC transport for the Polaris service management API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

import grpc
from polarismesh_specification.api.v1.service_manage import grpcapi_pb2_grpc, request_pb2, response_pb2, service_pb2

from polaris_python.core.config import Config
from polaris_python.core.error import PolarisTransportError
from polaris_python.plugin.connector import ServerConnector

logger = logging.getLogger(__name__)


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
        if not self.config.token:
            return ()
        token = self.config.token
        if not token.lower().startswith("bearer "):
            token = f"Bearer {token}"
        return (("authorization", token),)

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
        request: service_pb2.Instance,
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
                return await rpc(request, timeout=self.config.timeout_seconds, metadata=self._metadata())
            except grpc.aio.AioRpcError as exc:
                last_error = exc
                if exc.code() not in self._RETRYABLE_STATUS or attempt + 1 >= attempts:
                    break
                self._address_index = (self._address_index + 1) % len(self._addresses)
                await asyncio.sleep(self.config.retry_backoff_seconds * (2**attempt))
        raise PolarisTransportError(f"Polaris {method} failed: {last_error}") from last_error

    async def register_instance(self, instance: service_pb2.Instance) -> response_pb2.Response:
        """Call ``PolarisGRPC.RegisterInstance``."""
        return await self._unary("RegisterInstance", instance)

    async def deregister_instance(self, instance: service_pb2.Instance) -> response_pb2.Response:
        """Call ``PolarisGRPC.DeregisterInstance``."""
        return await self._unary("DeregisterInstance", instance)

    async def heartbeat(self, instance: service_pb2.Instance) -> response_pb2.Response:
        """Call ``PolarisGRPC.Heartbeat``."""
        return await self._unary("Heartbeat", instance)

    async def _request_once(
        self, address: str, request: request_pb2.DiscoverRequest
    ) -> AsyncIterator[response_pb2.DiscoverResponse]:
        stub = await self._stub(address)

        async def requests() -> AsyncIterator[request_pb2.DiscoverRequest]:
            yield request
            await asyncio.Event().wait()

        stream = stub.Discover(requests(), timeout=None, metadata=self._metadata())
        async for response in stream:
            yield response

    async def _discover(self, request: request_pb2.DiscoverRequest) -> AsyncIterator[response_pb2.DiscoverResponse]:
        """Reconnect a discovery stream after transient endpoint failures."""
        if not self._addresses:
            raise PolarisTransportError("no Polaris server address configured")
        while not self._closed:
            address = self._addresses[self._address_index % len(self._addresses)]
            try:
                yielded = False
                async for response in self._request_once(address, request):
                    yielded = True
                    yield response
                if self._closed:
                    return
                await asyncio.sleep(
                    self.config.retry_backoff_seconds if yielded else max(self.config.retry_backoff_seconds, 0.05)
                )
            except grpc.aio.AioRpcError as exc:
                if exc.code() not in self._RETRYABLE_STATUS:
                    raise PolarisTransportError(f"Polaris Discover failed: {exc}") from exc
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
