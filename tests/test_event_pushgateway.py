# Tencent is pleased to support the open source community by making polaris-python available.
#
# Copyright (C) 2021 Tencent. All rights reserved.
# Licensed under the BSD 3-Clause License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://opensource.org/licenses/BSD-3-Clause
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Verify event batching, addressing and retry for the Pushgateway reporter."""

import asyncio
import json

import pytest
from aiohttp import web
from polarismesh_specification.api.v1.service_manage import service_pb2

from polaris import Configuration
from polaris.pkg.config.event import PushGatewayEventConfig
from polaris.pkg.model.context import ContextKeyEventCenter, new_value_context
from polaris.pkg.model.core import ServiceKey
from polaris.pkg.model.event import EventCenter, SDKEventName, SDKEventType, now_event
from polaris.pkg.model.service import Instance
from polaris.plugin.event.pushgateway import PushGatewayEventReporter
from polaris.plugin_manager import InitContext, PluginManager
from polaris import init_context_by_config
from examples._internal._ai_stub import AIStub
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection


def make_config(**options):
    config = Configuration()
    config.set_default()
    reporter = config.get_global().get_event_reporter()
    reporter.enable = True
    reporter.chain = ["pushgateway"]
    plugin = reporter.get_pushgateway()
    for name, value in options.items():
        setattr(plugin, name, value)
    plugin.verify()
    return config


def make_reporter(config):
    value_context = new_value_context()
    event_center = EventCenter(value_context)
    value_context.set_value(ContextKeyEventCenter, event_center)
    return PushGatewayEventReporter(InitContext(config=config, value_ctx=value_context,
                                                plugins=PluginManager())), event_center


def event(name=SDKEventName.ON_SERVICE_ADDED):
    return now_event("client", SDKEventType.INSTANCE, name, client_ip="127.0.0.1",
                     namespace="ns", service="svc", old_value=None, new_value=object())


class FakeEngine:
    def __init__(self, node=None):
        self.node = node

    async def _async_get_one_instance(self, request):
        assert (request.namespace, request.service) == ("Polaris", "polaris.pushgateway")
        return self.node


async def start_server(handler):
    app = web.Application()
    app.router.add_post("/{path:.*}", handler)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, port


@pytest.mark.asyncio
async def test_pushgateway_batches_events_to_explicit_address():
    received = []
    release = asyncio.Event()

    async def accept(request):
        received.append((request.path, request.headers.get("Content-Type"), await request.text()))
        release.set()
        return web.Response()

    runner, port = await start_server(accept)
    config = make_config(address=[f"127.0.0.1:{port}"], push_interval=10, max_batch_size=2)
    reporter, center = make_reporter(config)
    try:
        await reporter.start(FakeEngine())
        center.publish(event(SDKEventName.ON_SERVICE_ADDED))
        center.publish(event(SDKEventName.ON_SERVICE_UPDATED))
        await asyncio.wait_for(release.wait(), 2)
        await reporter.close()
        assert len(received) == 1
        path, content_type, body = received[0]
        assert path == "/polaris/client/events"
        assert content_type == "application/json"
        payload = json.loads(body)
        assert [item["event_name"] for item in payload["batch"]] == [
            SDKEventName.ON_SERVICE_ADDED, SDKEventName.ON_SERVICE_UPDATED,
        ]
        assert payload["batch"][0]["event_type"] == SDKEventType.INSTANCE
        assert payload["batch"][0]["client_id"] == "client"
        assert "old_value" not in payload["batch"][0]
    finally:
        await reporter.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_pushgateway_discovers_address_and_applies_override_host():
    received = []
    release = asyncio.Event()

    async def accept(request):
        received.append(request.path)
        release.set()
        return web.Response()

    runner, port = await start_server(accept)
    node = Instance(
        service_pb2.Instance(
            host={"value": "unreachable.example"}, port={"value": port}),
        ServiceKey("Polaris", "polaris.pushgateway"),
    )
    config = make_config(address=[], override_host="127.0.0.1", push_interval=10)
    reporter, center = make_reporter(config)
    try:
        await reporter.start(FakeEngine(node))
        center.publish(event())
        await asyncio.wait_for(release.wait(), 2)
        assert received == ["/polaris/client/events"]
    finally:
        await reporter.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_pushgateway_retries_failed_batch_and_succeeds():
    attempts = []
    release = asyncio.Event()

    async def accept(request):
        attempts.append(await request.text())
        if len(attempts) == 1:
            return web.Response(status=503)
        release.set()
        return web.Response()

    runner, port = await start_server(accept)
    config = make_config(address=[f"127.0.0.1:{port}"], push_interval=10,
                         max_retries=3, retry_interval=1)
    reporter, center = make_reporter(config)
    try:
        await reporter.start(FakeEngine())
        center.publish(event(SDKEventName.CIRCUIT_BREAKER_OPEN))
        await asyncio.wait_for(release.wait(), 3)
        assert len(attempts) == 2
        assert json.loads(attempts[0]) == json.loads(attempts[1])
    finally:
        await reporter.close()
        await runner.cleanup()


def test_pushgateway_drops_event_when_queue_is_full():
    config = make_config(event_queue_size=1)
    reporter, _ = make_reporter(config)
    reporter.queue = asyncio.Queue(maxsize=1)
    reporter.on_sdk_event(event())
    reporter.on_sdk_event(event(SDKEventName.ON_SERVICE_UPDATED))
    assert reporter.queue.qsize() == 1


def test_event_reporter_configuration_loads_yaml_and_code():
    config = Configuration.from_dict({"global": {"eventReporter": {
        "enable": True,
        "chain": ["pushgateway"],
        "plugin": {"pushgateway": {
            "address": ["127.0.0.1:9091"], "eventQueueSize": 8, "maxBatchSize": 2,
            "pushInterval": "10ms", "retryInterval": "1ms", "overrideHost": "127.0.0.2",
        }},
    }}}, apply_env=False)
    config.set_default()
    config.verify()
    plugin = config.get_global().get_event_reporter().get_pushgateway()
    assert isinstance(plugin, PushGatewayEventConfig)
    assert plugin.address == ["127.0.0.1:9091"]
    assert plugin.event_queue_size == 8
    assert plugin.max_batch_size == 2
    assert plugin.push_interval == 10
    assert plugin.retry_interval == 1
    assert plugin.override_host == "127.0.0.2"


@pytest.mark.asyncio
async def test_context_starts_and_closes_pushgateway_reporter(monkeypatch, tmp_path):
    received = []
    release = asyncio.Event()

    async def accept(request):
        received.append(await request.text())
        release.set()
        return web.Response()

    runner, port = await start_server(accept)
    stub = AIStub()

    async def fake_stub(connection, address):
        return stub

    monkeypatch.setattr(GrpcConnection, "_stub", fake_stub)
    config = make_config(address=[f"127.0.0.1:{port}"], push_interval=10)
    config.get_global().get_stat_reporter().enable = False
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "cache")
    context = init_context_by_config(config)
    try:
        assert len(context.engine.event_reporters) == 1
        context.get_event_center().publish(event())
        await asyncio.wait_for(release.wait(), 2)
        assert len(json.loads(received[0])["batch"]) == 1
    finally:
        context.destroy()
        await runner.cleanup()
    assert context.engine.event_reporters == []
