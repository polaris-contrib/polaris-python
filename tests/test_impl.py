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
from pathlib import Path

import pytest
from polarismesh_specification.api.v1.service_manage import (
    client_pb2,
    request_pb2,
    response_pb2,
    service_pb2,
)

from polaris.api.config import init_context_by_config
from polaris.api.consumer import ConsumerAPI
from polaris.pkg.config.api import Configuration
from polaris.pkg.model.service import GetInstancesRequest
from polaris.pkg.model import util
from polaris.pkg.flow import impl
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection


@pytest.fixture(autouse=True)
def offline_tcp_probe(monkeypatch):
    async def connect(host, port):
        raise OSError("offline TCP boundary")

    monkeypatch.setattr(util.asyncio, "open_connection", connect)


class FakePolarisStub:
    """Serve enough of the specification API for an Engine integration test."""

    async def ReportClient(self, request, timeout=None, metadata=()):
        del request, timeout, metadata
        return response_pb2.Response(
            code={"value": 200000},
            client=client_pb2.Client(location={"region": {"value": "r"}}),
        )

    def Discover(
        self,
        requests: AsyncIterator[request_pb2.DiscoverRequest],
        timeout=None,
        metadata=(),
    ) -> AsyncIterator[response_pb2.DiscoverResponse]:
        del timeout, metadata

        async def responses() -> AsyncIterator[response_pb2.DiscoverResponse]:
            async for request in requests:
                response = response_pb2.DiscoverResponse(
                    code={"value": 200000},
                    type=request.type,
                    service=service_pb2.Service(
                        name={"value": request.service.name.value},
                        namespace={"value": request.service.namespace.value},
                        revision={"value": f"revision-{request.type}"},
                    ),
                )
                if request.type == request_pb2.DiscoverRequest.INSTANCE:
                    response.instances.append(
                        service_pb2.Instance(
                            id={"value": "instance-1"},
                            service={"value": request.service.name.value},
                            namespace={"value": request.service.namespace.value},
                            host={"value": "127.0.0.1"},
                            port={"value": 8080},
                            weight={"value": 100},
                            healthy={"value": True},
                        )
                    )
                yield response

        return responses()


@pytest.mark.asyncio
async def test_engine_discovers_through_grpc_on_its_runtime_loop(monkeypatch, tmp_path):
    stub = FakePolarisStub()

    async def fake_stub(self, address):
        del self, address
        return stub

    monkeypatch.setattr(GrpcConnection, "_stub", fake_stub)
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = ["fake:8091"]
    config.get_global().get_api().max_retry_times = 1
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path)
    context = init_context_by_config(config)
    original_file_cache = context.get_engine().file_cache
    async def no_file_cache(self, request, expire=60):
        return None

    context.get_engine().file_cache = type(
        "MemoryFileCache",
        (),
        {"async_get": no_file_cache, "save": lambda self, request, response: None},
    )()
    consumer = ConsumerAPI(context)
    try:
        result = await consumer.async_get_instances(GetInstancesRequest(service="svc", namespace="ns"))
        assert [instance.get_id() for instance in result.get_instances()] == ["instance-1"]
        assert context.get_engine().loop is not None
    finally:
        context.destroy()
    assert context.is_destroy()
    assert context.get_engine().loop is None
    assert not original_file_cache.write_thread.is_alive()


def test_sdk_startup_uses_default_backup_and_log_directories(monkeypatch, tmp_path):
    async def fake_report(self, request):
        return response_pb2.Response(code={"value": 200000})

    monkeypatch.setattr(GrpcConnection, "report_client", fake_report)
    config = Configuration()
    config.set_default()
    context = init_context_by_config(config)
    engine = context.get_engine()
    try:
        assert Path(engine.file_cache.base_dir).resolve() == tmp_path / "polaris" / "backup"
        assert context.get_value_context().logger.file_path.parent == tmp_path / "polaris" / "log" / "base"
        assert Path(engine.file_cache.base_dir, "file_cache.lock").is_file()
    finally:
        context.destroy()
    assert engine.loop is None


@pytest.mark.asyncio
@pytest.mark.parametrize("expire_ms, expected_seconds", [(86400000, 3600), (5000, 2.5), (60000, 30)])
async def test_expiry_scan_interval_is_half_idle_threshold_capped_at_one_hour(
    monkeypatch, expire_ms, expected_seconds,
):
    config = Configuration()
    config.set_default()
    config.get_consumer().get_local_cache().service_expire_time = expire_ms
    intervals, scans = [], []

    async def sleep(interval):
        intervals.append(interval)
        if len(intervals) == 2:
            raise asyncio.CancelledError

    class Registry:
        async def expire_services(self):
            scans.append(True)

    monkeypatch.setattr(impl.asyncio, "sleep", sleep)
    engine = impl.Engine(config=config, registry=Registry())
    with pytest.raises(asyncio.CancelledError):
        await engine.timing_expire_cache_task()
    assert intervals == [expected_seconds, expected_seconds]
    assert scans == [True]


@pytest.mark.asyncio
async def test_expiry_scan_continues_after_cleanup_failure(monkeypatch):
    config = Configuration()
    config.set_default()
    intervals, scans = [], []

    async def sleep(interval):
        intervals.append(interval)
        if len(intervals) == 3:
            raise asyncio.CancelledError

    class Registry:
        async def expire_services(self):
            scans.append(True)
            if len(scans) == 1:
                raise OSError("cleanup failed")

    monkeypatch.setattr(impl.asyncio, "sleep", sleep)
    engine = impl.Engine(config=config, registry=Registry())
    with pytest.raises(asyncio.CancelledError):
        await engine.timing_expire_cache_task()
    assert len(intervals) == 3
    assert len(scans) == 2
