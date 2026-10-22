# Tencent is pleased to support the open source community by making polaris-python available.
#
# Copyright (C) 2021 Tencent. All rights reserved.
#
# Licensed under the BSD 3-Clause License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://opensource.org/licenses/BSD-3-Clause
#
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Low-level asynchronous gRPC connection management."""

from __future__ import annotations

import asyncio
import itertools
import time
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass

import grpc
from google.protobuf.message import Message
from polarismesh_specification.api.v1.service_manage import (
    client_pb2,
    grpcapi_pb2_grpc,
    request_pb2,
    response_pb2,
    service_pb2,
)

from polaris.pkg.model.error import ErrorCode, SDKError, response_code, ServerCode
from polaris.api.log import ContextLogger, get_logger

logger = get_logger("network")

_REQUEST_ID_PREFIX = {
    "RegisterInstance": "1",
    "DeregisterInstance": "2",
    "Heartbeat": "3",
    "ReportClient": "3",
    "Discover": "4",
    "ReportServiceContract": "5",
    "GetServiceContract": "6",
    "GetSkill": "1",
    "GetSkillList": "1",
    "DownloadSkill": "1",
}
_REQUEST_ID_SEEDS = {prefix: itertools.count(1) for prefix in set(_REQUEST_ID_PREFIX.values())}


def _request_id(method: str) -> tuple[tuple[str, str], ...]:
    prefix = _REQUEST_ID_PREFIX.get(method)
    if prefix is None:
        return ()
    return (("request-id", f"{prefix}{next(_REQUEST_ID_SEEDS[prefix])}"),)


@dataclass(frozen=True, slots=True)
class GrpcSettings:
    """Values required by the gRPC transport."""

    addresses: Sequence[str]
    timeout_seconds: float
    token: str = ""
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.1
    refresh_interval_seconds: float = 2.0
    switch_interval_seconds: float | None = None
    credentials: grpc.ChannelCredentials | None = None


class GrpcConnection:
    """Manage channels, endpoint rotation, retries and discovery streams."""

    _RETRYABLE_STATUS = {
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
    }

    def __init__(self, settings: GrpcSettings, context_logger=None, stub_factory=None) -> None:
        self.settings = settings
        self.logger = (context_logger.get_logger("network") if isinstance(context_logger, ContextLogger)
                       else context_logger if context_logger is not None else logger)
        self._addresses = [address.strip() for address in settings.addresses if address.strip()]
        self._channels: dict[str, grpc.aio.Channel] = {}
        self._stubs: dict[str, grpcapi_pb2_grpc.PolarisGRPCStub] = {}
        self._stub_factory = stub_factory or grpcapi_pb2_grpc.PolarisGRPCStub
        self._contract_stubs = {}
        self._address_index = 0
        self._lock = asyncio.Lock()
        self._closed = False
        self.stat_reporter = None
        self.target_service = ("Polaris", "polaris.discover")
        self.address_resolver = None
        self.on_switch = None
        self._switch_task = None

    def _metadata(self) -> tuple[tuple[str, str], ...]:
        if not self.settings.token:
            return ()
        return (("x-polaris-token", self.settings.token),)

    async def _stub(self, address: str) -> grpcapi_pb2_grpc.PolarisGRPCStub:
        async with self._lock:
            if self._closed:
                raise SDKError(ErrorCode.ErrCodeInvalidStateError, "gRPC connector has been closed")
            if address not in self._stubs:
                channel = (grpc.aio.secure_channel(address, self.settings.credentials)
                           if self.settings.credentials is not None else grpc.aio.insecure_channel(address))
                self._channels[address] = channel
                self._stubs[address] = self._stub_factory(channel)
            return self._stubs[address]

    async def _rpc_stub(self, method, address):
        stub = await self._stub(address)
        if method not in ("ReportServiceContract", "GetServiceContract") or hasattr(stub, method):
            return stub
        if address not in self._contract_stubs:
            self._contract_stubs[address] = grpcapi_pb2_grpc.PolarisServiceContractGRPCStub(self._channels[address])
        return self._contract_stubs[address]

    async def _unary(
        self,
        method: str,
        request: Message,
        extra_metadata: tuple[tuple[str, str], ...] = (),
        timeout_seconds: float | None = None,
    ) -> response_pb2.Response:
        if not self._addresses:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "no Polaris server address configured")
        last_error: Exception | None = None
        attempts = self.settings.retry_attempts + 1
        for attempt in range(attempts):
            address = self._addresses[self._address_index % len(self._addresses)]
            started = time.monotonic()
            response = None
            try:
                stub = await self._rpc_stub(method, address)
                rpc: Callable[..., Awaitable[response_pb2.Response]] = getattr(stub, method)
                response = await rpc(
                    request,
                    timeout=self.settings.timeout_seconds if timeout_seconds is None else timeout_seconds,
                    metadata=_request_id(method) + extra_metadata + self._metadata(),
                )
                return response
            except grpc.aio.AioRpcError as exc:
                last_error = exc
                if exc.code() not in self._RETRYABLE_STATUS or attempt + 1 >= attempts:
                    break
                self._address_index = (self._address_index + 1) % len(self._addresses)
                self.logger.warning(
                    "Polaris %s on %s failed with %s; retrying on %s",
                    method,
                    address,
                    exc.code().name,
                    self._addresses[self._address_index],
                )
                await asyncio.sleep(self.settings.retry_backoff_seconds * (2**attempt))
            finally:
                if method in {"RegisterInstance", "DeregisterInstance", "Heartbeat",
                              "ReportServiceContract", "GetServiceContract"}:
                    self._report_call(method, address, started, response)
        raise SDKError(ErrorCode.ErrCodeNetworkError, f"Polaris {method} failed: {last_error}") from last_error

    async def switch_address(self):
        """Move subsequent calls and streams to the next configured endpoint."""
        if len(self._addresses) < 2:
            return
        previous = self._addresses[self._address_index % len(self._addresses)]
        self._address_index = (self._address_index + 1) % len(self._addresses)
        current = self._addresses[self._address_index]
        self.logger.info("server connection switched from %s to %s", previous, current)
        if self.on_switch is not None:
            try:
                await self.on_switch()
            except Exception:
                self.logger.warning("server switch callback failed: %s", traceback.format_exc())

    def start_switching(self, loop=None):
        """Start periodic endpoint rotation on the context's event loop."""
        if (self._closed or self._switch_task is not None
                or self.settings.switch_interval_seconds is None or len(self._addresses) < 2):
            return
        loop = loop or asyncio.get_running_loop()
        self._switch_task = loop.create_task(self._switch_loop(), name="polaris-server-switch")

    async def _switch_loop(self):
        interval = self.settings.switch_interval_seconds
        while not self._closed:
            await asyncio.sleep(interval)
            if self._closed:
                return
            await self.switch_address()

    async def stop_switching(self):
        """Stop endpoint rotation before the connection closes."""
        if self._switch_task is not None:
            self._switch_task.cancel()
            await asyncio.gather(self._switch_task, return_exceptions=True)
            self._switch_task = None

    def _report_call(self, method, address, started, response):
        if self.stat_reporter is None:
            return
        from polaris.pkg.model.service import ServiceCallResult, RetStatus
        from polaris.pkg.model.util import get_ip_from_int_with_port
        host, port = get_ip_from_int_with_port(address)
        code = response_code(response) if response is not None else ErrorCode.ErrCodeNetworkError
        accepted = {ServerCode.ExecuteSuccess}
        if method == "RegisterInstance":
            accepted.add(ServerCode.ExistedResource)
        if method == "DeregisterInstance":
            accepted.add(ServerCode.NotFoundResource)
        success = code in accepted
        names = {"RegisterInstance": "register", "DeregisterInstance": "deRegister", "Heartbeat": "heartbeat",
                 "ReportServiceContract": "reportServiceContract", "GetServiceContract": "getServiceContract"}
        self.stat_reporter.report(ServiceCallResult(
            namespace=self.target_service[0], service=self.target_service[1], host=host, port=port,
            method=names[method], ret_code=0 if success else ErrorCode.ErrCodeServerError if response is not None else code,
            ret_status=RetStatus.RetSuccess if success else RetStatus.RetFail,
            delay=int((time.monotonic() - started) * 1000),
        ))

    async def register_instance(self, instance: service_pb2.Instance,
                                auto_heartbeat: bool = False) -> response_pb2.Response:
        """Register an instance using the headers sent by polaris-java."""
        metadata = (("async-regis", "true"),) if auto_heartbeat else ()
        return await self._unary("RegisterInstance", instance, metadata)

    async def deregister_instance(self, instance: service_pb2.Instance) -> response_pb2.Response:
        """Deregister an instance."""
        return await self._unary("DeregisterInstance", instance)

    async def heartbeat(self, instance: service_pb2.Instance) -> response_pb2.Response:
        """Report an instance heartbeat."""
        return await self._unary("Heartbeat", instance)

    async def report_client(self, client: client_pb2.Client) -> response_pb2.Response:
        """Report this SDK client."""
        return await self._unary("ReportClient", client)

    async def _request_once(
        self,
        address: str,
        request: request_pb2.DiscoverRequest,
    ) -> AsyncIterator[response_pb2.DiscoverResponse]:
        stub = await self._stub(address)
        pending = request_pb2.DiscoverRequest()
        pending.CopyFrom(request)
        request_reader = None

        async def requests() -> AsyncIterator[request_pb2.DiscoverRequest]:
            nonlocal request_reader
            request_reader = asyncio.current_task()
            while not self._closed:
                outgoing = request_pb2.DiscoverRequest()
                outgoing.CopyFrom(pending)
                yield outgoing
                await asyncio.sleep(self.settings.refresh_interval_seconds)

        request_stream = requests()
        stream = stub.Discover(request_stream, timeout=None, metadata=_request_id("Discover") + self._metadata())
        try:
            async for response in stream:
                revision = response.service.revision.value
                if revision:
                    pending.service.revision.value = revision
                yield response
        finally:
            cancel = getattr(stream, "cancel", None)
            if cancel is not None:
                cancel()
            else:
                close = getattr(stream, "aclose", None)
                if close is not None:
                    await close()
            # gRPC consumes requests on its own task; wait for cancellation before closing the generator.
            if request_reader is not None and request_reader is not asyncio.current_task():
                if not request_reader.done():
                    request_reader.cancel()
                await asyncio.gather(request_reader, return_exceptions=True)
            await request_stream.aclose()

    async def discover(
        self,
        request: request_pb2.DiscoverRequest,
    ) -> AsyncIterator[response_pb2.DiscoverResponse]:
        """Open a reconnecting discovery stream."""
        if not self._addresses:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "no Polaris server address configured")
        failing = False
        while not self._closed:
            if self.address_resolver is not None:
                await self.address_resolver()
            address = self._addresses[self._address_index % len(self._addresses)]
            try:
                session = self._request_once(address, request)
                try:
                    async for response in session:
                        if failing:
                            self.logger.info("Discover reconnected to %s", address)
                            failing = False
                        yield response
                finally:
                    await session.aclose()
                if not self._closed:
                    await asyncio.sleep(self.settings.retry_backoff_seconds)
            except grpc.aio.AioRpcError as exc:
                if exc.code() not in self._RETRYABLE_STATUS:
                    raise SDKError(ErrorCode.ErrCodeNetworkError, f"Polaris Discover failed: {exc}") from exc
                if not failing:
                    self.logger.warning("Discover on %s failed with %s; reconnecting", address, exc.code().name)
                    failing = True
                self._address_index = (self._address_index + 1) % len(self._addresses)
                await asyncio.sleep(self.settings.retry_backoff_seconds)

    async def close(self) -> None:
        """Close every channel owned by this connection."""
        self._closed = True
        if self._switch_task is not None:
            self._switch_task.cancel()
            switch_task = self._switch_task
            self._switch_task = None
            await asyncio.gather(switch_task, return_exceptions=True)
        channels = list(self._channels.values())
        self._channels.clear()
        self._stubs.clear()
        self._contract_stubs.clear()
        for channel in channels:
            await channel.close()
