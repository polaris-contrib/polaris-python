from __future__ import annotations

import asyncio
import os
import socket
import time
from pathlib import Path

import pytest
from polarismesh_specification.api.v1.service_manage import client_pb2, response_pb2

from polaris_python.api.context import SDKContext
from polaris_python.api.report import sdk_version
from polaris_python.core.config import Config
from polaris_python.plugin.registry import InMemoryRegistry


class ReportConnector:
    """Answer ReportClient with a location, or with ``code`` when given."""

    def __init__(self, code: int = 200000) -> None:
        self.code = code
        self.reports: list[client_pb2.Client] = []

    async def report_client(self, client: client_pb2.Client) -> response_pb2.Response:
        self.reports.append(client)
        return response_pb2.Response(
            code={"value": self.code},
            client=client_pb2.Client(location={"region": {"value": "south"}, "zone": {"value": "gz"}}),
        )

    async def close(self) -> None:
        pass


def _context(connector: ReportConnector, **config: object) -> SDKContext:
    return SDKContext(Config(namespace="prod", **config), connector=connector, registry=InMemoryRegistry())


@pytest.mark.asyncio
async def test_context_reports_client_once_at_start() -> None:
    connector = ReportConnector()
    context = _context(connector, bind_ip="10.0.0.8")

    await asyncio.sleep(0.05)

    [client] = connector.reports
    assert client.host.value == "10.0.0.8"
    assert client.version.value == sdk_version()
    assert client.id.value.startswith(f"{socket.gethostname()}_{os.getpid()}_")
    await context.async_destroy()


@pytest.mark.asyncio
async def test_report_returns_the_location_polaris_resolved() -> None:
    connector = ReportConnector()
    context = _context(connector, report_enable=False)

    response = await context.client_reporter.report_once()

    assert response is not None
    assert response.client.location.zone.value == "gz"
    await context.async_destroy()


@pytest.mark.asyncio
async def test_failed_report_is_logged_and_does_not_raise(tmp_path: Path) -> None:
    context = _context(ReportConnector(code=500000), report_enable=False, log_dir=str(tmp_path))

    assert await context.client_reporter.report_once() is None
    assert "Report client failed" in (tmp_path / "base" / "polaris.log").read_text(encoding="utf-8")
    await context.async_destroy()


@pytest.mark.asyncio
async def test_report_address_is_the_local_end_of_a_connection_to_the_server() -> None:
    server = await asyncio.start_server(lambda _reader, writer: writer.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    connector = ReportConnector()
    context = _context(connector, report_enable=False, server_addresses=[f"127.0.0.1:{port}"])

    await context.client_reporter.report_once()

    assert connector.reports[0].host.value == "127.0.0.1"
    server.close()
    await server.wait_closed()
    await context.async_destroy()


@pytest.mark.asyncio
async def test_report_can_be_disabled() -> None:
    connector = ReportConnector()
    context = _context(connector, report_enable=False)

    await asyncio.sleep(0.05)

    assert connector.reports == []
    await context.async_destroy()


@pytest.mark.asyncio
async def test_destroy_stops_reporting() -> None:
    context = _context(ReportConnector())
    task = context.client_reporter._task

    await context.async_destroy()

    assert task is not None and task.done()


def test_sync_context_starts_reporting_on_first_api_call() -> None:
    from polaris_python.api.provider import ProviderAPI
    from polaris_python.core.instance import ServiceInstance

    class SyncConnector(ReportConnector):
        async def register_instance(self, instance: object) -> response_pb2.Response:
            return response_pb2.Response(code={"value": 200000})

        async def deregister_instance(self, instance: object) -> response_pb2.Response:
            return response_pb2.Response(code={"value": 200000})

    connector = SyncConnector()
    context = _context(connector)
    assert connector.reports == []

    provider = ProviderAPI(context)
    instance = ServiceInstance(service="svc", host="127.0.0.1", port=8080)
    provider.register_instance(instance)
    deadline = time.monotonic() + 1
    while not connector.reports and time.monotonic() < deadline:
        time.sleep(0.01)
    provider.deregister_instance(instance)

    assert len(connector.reports) == 1
    context.destroy()
