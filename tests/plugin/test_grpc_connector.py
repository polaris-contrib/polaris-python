from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from polarismesh_specification.api.v1.service_manage import client_pb2, request_pb2, response_pb2, service_pb2

from polaris_python.core.config import Config
from polaris_python.plugin.grpc import GrpcConnector


class FakeDiscoverStub:
    """Answer each DiscoverRequest once, like the Polaris server."""

    def __init__(self) -> None:
        self.requests: list[request_pb2.DiscoverRequest] = []

    def Discover(  # noqa: N802 - generated stub method name
        self,
        requests: AsyncIterator[request_pb2.DiscoverRequest],
        timeout: float | None = None,
        metadata: object = None,
    ) -> AsyncIterator[response_pb2.DiscoverResponse]:
        async def responses() -> AsyncIterator[response_pb2.DiscoverResponse]:
            async for request in requests:
                self.requests.append(request)
                yield response_pb2.DiscoverResponse(
                    code={"value": 200000},
                    type=response_pb2.DiscoverResponse.RATE_LIMIT,
                    service=service_pb2.Service(revision={"value": f"rev-{len(self.requests)}"}),
                )

        return responses()


@pytest.mark.asyncio
async def test_discover_resends_request_with_last_revision() -> None:
    connector = GrpcConnector(Config(server_addresses=["fake:8091"], refresh_interval_seconds=0.01))
    stub = FakeDiscoverStub()

    async def fake_stub(_address: str) -> FakeDiscoverStub:
        return stub

    connector._stub = fake_stub  # type: ignore[method-assign]
    request = request_pb2.DiscoverRequest(
        type=request_pb2.DiscoverRequest.RATE_LIMIT,
        service=service_pb2.Service(name={"value": "svc"}, namespace={"value": "ns"}),
    )

    stream = connector.discover(request)
    await anext(stream)
    await anext(stream)
    await anext(stream)
    await stream.aclose()

    assert [item.service.revision.value for item in stub.requests[:3]] == ["", "rev-1", "rev-2"]
    assert request.service.revision.value == ""


class FakeUnaryStub:
    """Record the request and metadata of each unary call."""

    def __init__(self) -> None:
        self.calls: dict[str, tuple[object, dict[str, str]]] = {}

    def _record(self, method: str) -> object:
        async def call(
            request: object, timeout: float | None = None, metadata: tuple[tuple[str, str], ...] = ()
        ) -> response_pb2.Response:
            self.calls[method] = (request, dict(metadata))
            return response_pb2.Response(code={"value": 200000})

        return call

    def __getattr__(self, method: str) -> object:
        return self._record(method)


def _unary_connector(**config: object) -> tuple[GrpcConnector, FakeUnaryStub]:
    connector = GrpcConnector(Config(server_addresses=["fake:8091"], **config))
    stub = FakeUnaryStub()

    async def fake_stub(_address: str) -> FakeUnaryStub:
        return stub

    connector._stub = fake_stub  # type: ignore[method-assign]
    return connector, stub


@pytest.mark.asyncio
async def test_register_sends_java_headers() -> None:
    connector, stub = _unary_connector(token="secret")

    await connector.register_instance(service_pb2.Instance())

    headers = stub.calls["RegisterInstance"][1]
    assert headers["async-regis"] == "true"
    assert headers["x-polaris-token"] == "secret"
    assert headers["request-id"].startswith("1")


@pytest.mark.asyncio
async def test_report_client_calls_report_client_rpc() -> None:
    connector, stub = _unary_connector()
    client = client_pb2.Client(host={"value": "10.0.0.8"})

    await connector.report_client(client)

    request, headers = stub.calls["ReportClient"]
    assert request == client
    assert headers["request-id"].startswith("3")
    assert "x-polaris-token" not in headers
