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

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import grpc
import pytest
from polarismesh_specification.api.v1.service_manage import grpcapi_pb2_grpc, request_pb2, response_pb2, service_pb2

from polaris.api import log
from polaris.pkg.config.api import Configuration
from polaris.pkg.model.server import InstanceDiscoverRequest, InstanceRegisterRequest
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection, GrpcSettings
from polaris.plugin.server_connector.grpc_connector.grpc_client import GrpcConnector
from polaris.plugin_manager import InitContext


class FakeDiscoverStub:
    """Answer each discovery request once."""

    def __init__(self) -> None:
        self.requests: list[request_pb2.DiscoverRequest] = []

    def Discover(
        self,
        requests: AsyncIterator[request_pb2.DiscoverRequest],
        timeout: float | None = None,
        metadata: object = None,
    ) -> AsyncIterator[response_pb2.DiscoverResponse]:
        del timeout, metadata

        async def responses() -> AsyncIterator[response_pb2.DiscoverResponse]:
            async for request in requests:
                self.requests.append(request)
                yield response_pb2.DiscoverResponse(
                    code={"value": 200000},
                    service=service_pb2.Service(revision={"value": f"rev-{len(self.requests)}"}),
                )

        return responses()


@pytest.mark.asyncio
async def test_discover_resends_last_revision() -> None:
    connection = GrpcConnection(
        GrpcSettings(addresses=["fake:8091"], timeout_seconds=1, refresh_interval_seconds=0.001)
    )
    stub = FakeDiscoverStub()

    async def fake_stub(_address: str) -> FakeDiscoverStub:
        return stub

    connection._stub = fake_stub  # type: ignore[method-assign]
    request = request_pb2.DiscoverRequest(
        type=request_pb2.DiscoverRequest.INSTANCE,
        service=service_pb2.Service(name={"value": "svc"}, namespace={"value": "ns"}),
    )
    stream = connection.discover(request)
    await anext(stream)
    await anext(stream)
    await stream.aclose()

    assert [item.service.revision.value for item in stub.requests[:2]] == ["", "rev-1"]


class FakeUnaryStub:
    """Record unary request metadata."""

    def __init__(self) -> None:
        self.metadata: dict[str, str] = {}

    async def RegisterInstance(self, request, timeout=None, metadata=()):
        del request, timeout
        self.metadata = dict(metadata)
        return response_pb2.Response(code={"value": 200000})


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_heartbeat", [False, True])
async def test_register_sends_java_headers(auto_heartbeat) -> None:
    connection = GrpcConnection(
        GrpcSettings(addresses=["fake:8091"], timeout_seconds=1, token="secret")
    )
    stub = FakeUnaryStub()

    async def fake_stub(_address: str) -> FakeUnaryStub:
        return stub

    connection._stub = fake_stub  # type: ignore[method-assign]
    await connection.register_instance(service_pb2.Instance(), auto_heartbeat=auto_heartbeat)

    assert stub.metadata.get("async-regis") == ("true" if auto_heartbeat else None)
    assert stub.metadata["x-polaris-token"] == "secret"
    assert stub.metadata["request-id"].startswith("1")


class FakeConnection:
    """Record adapter messages without performing I/O."""

    def __init__(self) -> None:
        self.instance = None

    async def register_instance(self, instance, auto_heartbeat=False):
        self.instance = instance
        return response_pb2.Response(
            code={"value": 200000},
            instance=service_pb2.Instance(id={"value": "registered-id"}),
        )


@pytest.mark.asyncio
async def test_periodic_address_switch_invokes_callback():
    switched = asyncio.Event()
    connection = GrpcConnection(
        GrpcSettings(addresses=["first:8091", "second:8091"], timeout_seconds=1,
                     switch_interval_seconds=0.01),
    )

    async def callback():
        switched.set()

    connection.on_switch = callback
    connection.start_switching()
    try:
        await asyncio.wait_for(switched.wait(), 1)
        assert connection._address_index == 1
    finally:
        await connection.close()
    assert connection._switch_task is None


@pytest.mark.asyncio
async def test_address_switch_closes_streams_owned_by_connection():
    config = Configuration()
    config.set_default()
    connector = GrpcConnector(InitContext(config=config))
    connection = GrpcConnection(GrpcSettings(addresses=["first:8091", "second:8091"], timeout_seconds=1))
    closed = asyncio.Event()

    class Stream:
        async def aclose(self):
            closed.set()

    stream = Stream()
    connector._streams["ns\\x00svc\\x001"] = stream
    connector._stream_connections["ns\\x00svc\\x001"] = connection
    await connector._on_address_switched(connection)
    await asyncio.wait_for(closed.wait(), 1)
    assert connector._streams == {}
    assert connector._stream_connections == {}


@pytest.mark.asyncio
async def test_unary_retry_logs_to_context_network_category(tmp_path):
    context_log = log.ContextLogger("client", log.LogOptions(log_dir=tmp_path))
    connection = GrpcConnection(
        GrpcSettings(addresses=["first:8091", "second:8091"], timeout_seconds=1,
                     retry_attempts=1, retry_backoff_seconds=0),
        context_logger=context_log,
    )

    class Stub:
        async def RegisterInstance(self, request, timeout=None, metadata=()):
            if connection._address_index == 0:
                raise grpc.aio.AioRpcError(grpc.StatusCode.UNAVAILABLE, (), (), "offline")
            return response_pb2.Response(code={"value": 200000})

    async def stub(address):
        return Stub()

    connection._stub = stub
    try:
        response = await connection.register_instance(service_pb2.Instance())
        assert response.code.value == 200000
        network = context_log.get_logger("network")
        assert connection.logger is network
        assert "[clientId=client] Polaris RegisterInstance on first:8091 failed with UNAVAILABLE" in (
            network.file_path.read_text())
        assert "retrying on second:8091" in network.file_path.read_text()
        assert "retrying" not in context_log.file_path.read_text()
    finally:
        await connection.close()
        context_log.close()


@pytest.mark.asyncio
async def test_plugin_adapter_converts_internal_register_request() -> None:
    config = Configuration()
    config.set_default()
    connector = GrpcConnector(InitContext(config=config))
    connection = FakeConnection()
    connector.connection = connection

    response = await connector.register_instance(
        InstanceRegisterRequest("svc", "service-token", "ns", "127.0.0.1", 8080, protocol="http")
    )

    assert response.instance_id == "registered-id"
    assert connection.instance.service.value == "svc"
    assert connection.instance.namespace.value == "ns"
    assert connection.instance.protocol.value == "http"
    assert not connection.instance.HasField("health_check")


@pytest.mark.asyncio
async def test_stop_discover_closes_only_selected_resource_and_releases_lock():
    config = Configuration()
    config.set_default()
    connector = GrpcConnector(InitContext(config=config))
    opened, closed = [], []

    async def responses(request):
        key = (request.service.namespace.value, request.service.name.value, request.type)
        opened.append(key)
        try:
            while True:
                yield response_pb2.DiscoverResponse(code={"value": 200000})
        finally:
            closed.append(key)

    connector.connection.discover = responses
    first = InstanceDiscoverRequest(1, "svc", "ns")
    rule = InstanceDiscoverRequest(3, "svc", "ns")
    other = InstanceDiscoverRequest(1, "other", "ns")
    try:
        for request in (first, rule, other):
            await connector.discover(request)
        await connector.stop_discover(first)
        await connector.stop_discover(first)
        assert closed == [("ns", "svc", 1)]
        assert connector._stream_key(first) not in connector._stream_locks
        assert len(connector._streams) == 2
        assert not connector.connection._closed
        await connector.discover(first)
        assert opened.count(("ns", "svc", 1)) == 2
    finally:
        await connector.close()
    assert len(closed) == 4


@pytest.mark.asyncio
async def test_stop_discover_cleans_up_after_cancelled_pending_reader():
    config = Configuration()
    config.set_default()
    connector = GrpcConnector(InitContext(config=config))
    started, closed = asyncio.Event(), asyncio.Event()

    async def responses(request):
        try:
            started.set()
            await asyncio.Event().wait()
            yield response_pb2.DiscoverResponse(code={"value": 200000})
        finally:
            closed.set()

    connector.connection.discover = responses
    request = InstanceDiscoverRequest(1, "svc", "ns")
    reading = asyncio.create_task(connector.discover(request))
    await started.wait()
    reading.cancel()
    await asyncio.gather(reading, return_exceptions=True)
    await connector.stop_discover(request)
    assert closed.is_set()
    assert connector._streams == connector._stream_locks == {}
    await connector.close()


@pytest.mark.asyncio
async def test_discover_timeout_drops_closed_generator_and_can_reopen():
    config = Configuration()
    config.set_default()
    connector = GrpcConnector(InitContext(config=config))
    attempts = []
    closed = []

    async def responses(request):
        attempts.append(request)
        try:
            if len(attempts) == 1:
                await asyncio.Event().wait()
            yield response_pb2.DiscoverResponse(code={"value": 200000})
        finally:
            closed.append(request)

    connector.connection.discover = responses
    request = InstanceDiscoverRequest(1, "svc", "ns")
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(connector.discover(request), 0.02)
        assert connector._streams == {}
        assert len(closed) == 1
        assert (await connector.discover(request)).code.value == 200000
        assert len(attempts) == 2
    finally:
        await connector.close()
    assert len(closed) == 2


@pytest.mark.asyncio
async def test_stop_discover_cancels_real_grpc_call_and_reopens_resource():
    stopped = asyncio.Queue()

    class Server(grpcapi_pb2_grpc.PolarisGRPCServicer):
        async def Discover(self, requests, context):
            try:
                async for request in requests:
                    yield response_pb2.DiscoverResponse(code={"value": 200000}, type=request.type,
                        service=service_pb2.Service(revision={"value": "revision-1"}))
            finally:
                stopped.put_nowait(True)

    server = grpc.aio.server()
    grpcapi_pb2_grpc.add_PolarisGRPCServicer_to_server(Server(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = [f"127.0.0.1:{port}"]
    connector = GrpcConnector(InitContext(config=config))
    request = InstanceDiscoverRequest(1, "svc", "ns")
    try:
        assert (await connector.discover(request)).service.revision.value == "revision-1"
        await connector.stop_discover(request)
        assert await asyncio.wait_for(stopped.get(), 3)
        assert connector._streams == connector._stream_locks == {}
        assert (await connector.discover(request)).service.revision.value == "revision-1"
        await connector.stop_discover(request)
        assert await asyncio.wait_for(stopped.get(), 3)
    finally:
        await connector.close()
        await server.stop(None)
