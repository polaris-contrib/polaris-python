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
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for Java-compatible lossless online/offline."""

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp import ClientSession, web
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2
from polarismesh_specification.api.v1.traffic_manage import lossless_pb2

from polaris import (
    Configuration,
    ConsumerAPI,
    LosslessInstance,
    ProviderAPI,
    RegisterStatus,
    init_context_by_config,
)
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection
from polaris.pkg.config.api import LosslessConfig
from polaris.pkg.flow.lossless import LosslessManager, lossless_http_handlers
from polaris.pkg.model.lossless import InstanceProperties, LosslessActionProvider
from polaris.pkg.model.server import InstanceRegisterRequest
from polaris.pkg.model.service import GetInstancesRequest, GetOneInstanceRequest


class FakeActionProvider(LosslessActionProvider):
    def __init__(self, healthy_after=0):
        self.register_count = 0
        self.deregister_count = 0
        self.check_count = 0
        self.healthy_after = healthy_after

    def get_name(self):
        return "fake"

    async def do_register(self, instance_properties: InstanceProperties):
        self.register_count += 1

    async def do_deregister(self):
        self.deregister_count += 1

    def is_enable_health_check(self):
        return True

    async def do_health_check(self):
        self.check_count += 1
        return self.check_count >= self.healthy_after


class FakeConnector:
    def __init__(self, rules=None):
        self.rules = rules or []
        self.discover_count = 0

    async def discover(self, request):
        self.discover_count += 1
        response = response_pb2.DiscoverResponse()
        response.losslessRuleList.extend(self.rules)
        return response


def lossless_configuration(**kwargs):
    config = Configuration()
    config.set_default()
    config.get_provider().lossless = LosslessConfig(**kwargs)
    config.get_provider().lossless.set_default()
    return config


def instance_request():
    return InstanceRegisterRequest(
        namespace="ns", service="svc", service_token="token", host="127.0.0.1", port=8080,
    )


def lossless_instance():
    return LosslessInstance(namespace="ns", service="svc", host="127.0.0.1", port=8080)


def lossless_rule(**delay):
    rule = lossless_pb2.LosslessRule(namespace="ns", service="svc")
    rule.losslessOnline.delayRegister.SetInParent()
    for key, value in delay.items():
        setattr(rule.losslessOnline.delayRegister, key, value)
    return rule


@pytest.mark.asyncio
async def test_delay_register_waits_before_registration():
    manager = LosslessManager(lossless_configuration(enable=True, delay_register_interval=50), FakeConnector())
    provider = FakeActionProvider()
    manager.set_action_provider(lossless_instance(), provider)
    await manager.lossless_register(lossless_instance())
    assert provider.register_count == 0
    await asyncio.sleep(0.15)
    assert provider.register_count == 1
    assert manager.check_register_status() == RegisterStatus.REGISTERED


@pytest.mark.asyncio
async def test_health_check_register_polls_until_ready():
    config = lossless_configuration(
        enable=True, strategy=LosslessConfig.DELAY_BY_HEALTH_CHECK, health_check_interval=1,
    )
    manager = LosslessManager(config, FakeConnector())
    provider = FakeActionProvider(healthy_after=2)
    manager.set_action_provider(lossless_instance(), provider)
    await manager.lossless_register(lossless_instance())
    await asyncio.sleep(0.05)
    assert provider.check_count >= 2
    assert provider.register_count == 1


@pytest.mark.asyncio
async def test_disabled_lossless_registers_directly():
    manager = LosslessManager(lossless_configuration(enable=False), FakeConnector())
    provider = FakeActionProvider()
    manager.set_action_provider(lossless_instance(), provider)
    await manager.lossless_register(lossless_instance())
    assert provider.register_count == 1


@pytest.mark.asyncio
async def test_server_rule_overrides_local_delay():
    rule = lossless_rule(enable=False)
    manager = LosslessManager(lossless_configuration(enable=True), FakeConnector([rule]))
    provider = FakeActionProvider()
    manager.set_action_provider(lossless_instance(), provider)
    await manager.lossless_register(lossless_instance())
    assert provider.register_count == 1
    assert manager._register_tasks == {}


@pytest.mark.asyncio
async def test_metadata_rule_matches_instance():
    rule = lossless_rule(intervalSecond=5)
    rule.metadata["version"] = "v2"
    other = lossless_rule(intervalSecond=60)
    manager = LosslessManager(lossless_configuration(enable=True), FakeConnector([rule, other]))
    matched = LosslessInstance("ns", "svc", "127.0.0.1", 8080, metadata={"version": "v2"})
    options = await manager.effective_options(matched)
    assert options.delay_register_interval_ms == 5000


@pytest.mark.asyncio
async def test_lossless_deregister_marks_unregistered():
    manager = LosslessManager(lossless_configuration(enable=True), FakeConnector())
    provider = FakeActionProvider()
    manager.set_action_provider(lossless_instance(), provider)
    await manager._do_register(lossless_instance())
    assert manager.check_register_status() == RegisterStatus.REGISTERED
    await manager.lossless_deregister(lossless_instance())
    assert provider.deregister_count == 1
    assert manager.check_register_status() == RegisterStatus.UNREGISTERED


@pytest.mark.asyncio
async def test_offline_endpoint_requires_loopback_and_deregisters():
    manager = LosslessManager(lossless_configuration(enable=True), FakeConnector())
    provider = FakeActionProvider()
    manager.set_action_provider(lossless_instance(), provider)
    await manager._do_register(lossless_instance())
    handlers = dict(((method, path), handler) for method, path, handler in lossless_http_handlers(manager))

    class Request:
        remote = "10.0.0.1"

    response = await handlers[("*", "/offline")](Request())
    assert response.status == 403

    class LocalRequest:
        remote = "127.0.0.1"

    response = await handlers[("*", "/offline")](LocalRequest())
    assert response.status == 200
    assert response.text == "ok"
    assert provider.deregister_count == 1
    assert manager.check_register_status() == RegisterStatus.UNREGISTERED


@pytest.mark.asyncio
async def test_readiness_endpoint_reports_registration_status():
    manager = LosslessManager(lossless_configuration(enable=True), FakeConnector())
    handlers = dict(((method, path), handler) for method, path, handler in lossless_http_handlers(manager))
    readiness = handlers[("GET", "/readiness")]

    assert (await readiness(None)).status == 404
    provider = FakeActionProvider()
    manager.set_action_provider(lossless_instance(), provider)
    assert (await readiness(None)).status == 503
    await manager._do_register(lossless_instance())
    response = await readiness(None)
    assert response.status == 200
    assert response.text == "REGISTERED"


def _warmup_snapshot(ctime, weight=100):
    from polaris.pkg.model.core import ServiceKey
    from polaris.pkg.model.service import Instance, ServiceInstances

    proto = service_pb2.Instance(
        id={"value": "node"}, host={"value": "127.0.0.1"}, port={"value": 8080},
        weight={"value": weight}, healthy={"value": True}, ctime={"value": ctime},
    )
    instance = Instance(proto, ServiceKey("ns", "svc"))
    return ServiceInstances(
        service=service_pb2.Service(name={"value": "svc"}, namespace={"value": "ns"}),
        instances=[instance],
    )


def _warmup_rule(interval=100, curvature=1, overload=False, threshold=0):
    rule = lossless_pb2.LosslessRule(namespace="ns", service="svc")
    warmup = rule.losslessOnline.warmup
    warmup.enable = True
    warmup.intervalSecond = interval
    warmup.curvature = curvature
    warmup.enableOverloadProtection = overload
    warmup.overloadProtectionThreshold = threshold
    return rule


def test_warmup_weights_ramp_by_uptime():
    manager = LosslessManager(lossless_configuration(enable=True), FakeConnector([_warmup_rule()]))
    manager._rules_cache[("ns", "svc")] = ([_warmup_rule()], "", 0.0)

    ctime = datetime.now(timezone.utc) - timedelta(seconds=50)
    snapshot = _warmup_snapshot(ctime.isoformat())
    adjusted = manager.apply_warmup_weights(snapshot)
    assert 50 <= adjusted.instances[0].get_weight() < 100
    assert snapshot.instances[0].get_weight() == 100

    old = _warmup_snapshot((datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat())
    assert manager.apply_warmup_weights(old).instances[0].get_weight() == 100


def test_warmup_overload_protection_skips_adjustment():
    rule = _warmup_rule(overload=True, threshold=50)
    manager = LosslessManager(lossless_configuration(enable=True), FakeConnector([rule]))
    manager._rules_cache[("ns", "svc")] = ([rule], "", 0.0)
    ctime = datetime.now(timezone.utc).isoformat()
    snapshot = _warmup_snapshot(ctime)
    assert manager.apply_warmup_weights(snapshot).instances[0].get_weight() == 100


def test_lossless_configuration_parses_java_yaml_keys():
    config = Configuration.from_dict({
        "provider": {"lossless": {
            "enable": True,
            "strategy": "DELAY_BY_HEALTH_CHECK",
            "delayRegisterInterval": "30s",
            "healthCheckInterval": "5s",
            "healthCheckPath": "/ready",
        }},
        "consumer": {"weightAdjust": {"enable": True, "chain": ["warmup"]}},
    }, apply_env=False)
    config.set_default()
    lossless = config.get_provider().get_lossless()
    assert lossless.is_enable()
    assert lossless.get_strategy() == "DELAY_BY_HEALTH_CHECK"
    assert lossless.get_delay_register_interval() == 30000
    assert lossless.get_health_check_interval() == 5000
    assert lossless.get_health_check_path() == "/ready"
    assert config.get_consumer().get_weight_adjust().get_chain() == ["warmup"]


def test_lossless_configuration_rejects_invalid_strategy():
    config = lossless_configuration(enable=True, strategy="DELAY_BY_MAGIC")
    with pytest.raises(Exception, match="strategy"):
        config.verify()


class RegisterStub:
    """Record provider lifecycle RPCs with Java-compatible responses."""

    def __init__(self, rules=None, instances=None):
        self.calls = []
        self.rules = list(rules or [])
        self.instances = list(instances or [])
        self.revision = 0

    def record(self, method, request):
        self.calls.append((method, request, threading.get_ident()))

    async def ReportClient(self, request, timeout=None, metadata=()):
        self.record("ReportClient", request)
        return response_pb2.Response(code={"value": 200000})

    def Discover(self, requests, timeout=None, metadata=()):
        async def responses():
            async for request in requests:
                self.record("Discover", request)
                while True:
                    self.revision += 1
                    response = response_pb2.DiscoverResponse(
                        code={"value": 200000}, type=request.type,
                        service=service_pb2.Service(
                            name={"value": request.service.name.value},
                            namespace={"value": request.service.namespace.value},
                            revision={"value": f"revision-{self.revision}"},
                        ),
                    )
                    if request.type == 103:
                        response.losslessRuleList.extend(self.rules)
                    else:
                        response.instances.extend(self.instances)
                    yield response
                    await asyncio.sleep(0.01)
        return responses()

    async def RegisterInstance(self, request, timeout=None, metadata=()):
        self.record("RegisterInstance", request)
        result = service_pb2.Instance()
        result.CopyFrom(request)
        result.id.value = "registered"
        result.ctime.value = datetime.now(timezone.utc).isoformat()
        self.instances.append(result)
        return response_pb2.Response(code={"value": 200000}, instance=result)

    async def DeregisterInstance(self, request, timeout=None, metadata=()):
        self.record("DeregisterInstance", request)
        self.instances = [
            instance for instance in self.instances
            if not (instance.id.value == request.id.value
                    or (instance.host.value == request.host.value
                        and instance.port.value == request.port.value))
        ]
        return response_pb2.Response(code={"value": 200000})


def make_context(monkeypatch, tmp_path, stub, *, provider=True, consumer=False, **lossless):
    async def fake_stub(connection, address):
        return stub

    monkeypatch.setattr(GrpcConnection, "_stub", fake_stub)
    data = {
        "global": {
            "api": {"bindIP": "127.0.0.1"},
            "serverConnector": {"addresses": ["registry:8091"]},
            "statReporter": {"enable": False},
            "admin": {"host": "127.0.0.1", "port": 0 if provider else -1},
        },
    }
    if provider:
        local = {"enable": True}
        local.update(lossless)
        data["provider"] = {"lossless": local}
    if consumer:
        data["consumer"] = {
            "localCache": {"serviceRefreshInterval": "10ms"},
            "weightAdjust": {"enable": True, "chain": ["warmup"]},
        }
    config = Configuration.from_dict(data, apply_env=False)
    config.set_default()
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path)
    return init_context_by_config(config)


@pytest.mark.asyncio
async def test_provider_api_lossless_register_and_deregister(monkeypatch, tmp_path):
    stub = RegisterStub()

    async def fake_stub(connection, address):
        return stub

    monkeypatch.setattr(GrpcConnection, "_stub", fake_stub)
    config = Configuration.from_dict({
        "global": {
            "api": {"bindIP": "127.0.0.1"},
            "serverConnector": {"addresses": ["registry:8091"]},
            "statReporter": {"enable": False},
            "admin": {"host": "127.0.0.1", "port": -1},
        },
        "provider": {"lossless": {"enable": True, "delayRegisterInterval": "50ms"}},
    }, apply_env=False)
    config.set_default()
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path)
    context = init_context_by_config(config)
    provider = ProviderAPI(context)
    request = instance_request()
    try:
        await provider.async_lossless_register(request)
        assert not any(call[0] == "RegisterInstance" for call in stub.calls)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not any(call[0] == "RegisterInstance" for call in stub.calls):
            await asyncio.sleep(0.01)
        assert any(call[0] == "RegisterInstance" for call in stub.calls)
        assert request.instance_id == "registered"

        await provider.async_lossless_deregister(request)
        assert any(call[0] == "DeregisterInstance" for call in stub.calls)
        deregister = next(call[1] for call in stub.calls if call[0] == "DeregisterInstance")
        assert deregister.id.value == "registered"
        assert context.engine.lossless_manager.check_register_status() == RegisterStatus.UNREGISTERED
    finally:
        context.destroy()


@pytest.mark.asyncio
async def test_admin_server_exposes_lossless_endpoints(monkeypatch, tmp_path):
    stub = RegisterStub()

    async def fake_stub(connection, address):
        return stub

    monkeypatch.setattr(GrpcConnection, "_stub", fake_stub)
    config = Configuration.from_dict({
        "global": {
            "api": {"bindIP": "127.0.0.1"},
            "serverConnector": {"addresses": ["registry:8091"]},
            "statReporter": {"enable": False},
            "admin": {"host": "127.0.0.1", "port": 0},
        },
        "provider": {"lossless": {"enable": True, "delayRegisterInterval": "10s"}},
    }, apply_env=False)
    config.set_default()
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path)
    context = init_context_by_config(config)
    provider = ProviderAPI(context)
    try:
        await provider.async_lossless_register(instance_request())
        engine = context.engine
        port = engine.admin_server.port
        assert port is not None and port > 0
        base = f"http://127.0.0.1:{port}"
        async with ClientSession() as client:
            async with client.get(f"{base}/readiness") as response:
                assert response.status == 503
                assert await response.text() == "UNREGISTERED"
            async with client.post(f"{base}/offline") as response:
                assert response.status == 200
                assert await response.text() == "ok"
            async with client.get(f"{base}/online") as response:
                assert response.status == 503
        assert any(call[0] == "DeregisterInstance" for call in stub.calls)
    finally:
        context.destroy()


@pytest.mark.asyncio
async def test_health_check_delay_and_readiness_transition(monkeypatch, tmp_path):
    stub = RegisterStub()
    ready = asyncio.Event()

    async def health(request):
        if ready.is_set():
            return web.Response(text="ready")
        return web.Response(status=503)

    app = web.Application()
    app.router.add_get("/ready", health)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    provider_port = site._server.sockets[0].getsockname()[1]

    context = make_context(
        monkeypatch, tmp_path, stub,
        strategy="DELAY_BY_HEALTH_CHECK", healthCheckInterval="10ms", healthCheckPath="/ready",
    )
    request = instance_request()
    request.port = provider_port
    provider = ProviderAPI(context)
    admin_port = context.engine.admin_server.port
    base = f"http://127.0.0.1:{admin_port}"
    try:
        await provider.async_lossless_register(request)
        async with ClientSession() as client:
            async with client.get(f"{base}/readiness") as response:
                assert response.status == 503
                assert await response.text() == "UNREGISTERED"
            assert not any(call[0] == "RegisterInstance" for call in stub.calls)

            ready.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not any(call[0] == "RegisterInstance" for call in stub.calls):
                await asyncio.sleep(0.01)
            assert any(call[0] == "RegisterInstance" for call in stub.calls)
            assert request.instance_id == "registered"

            async with client.get(f"{base}/readiness") as response:
                assert response.status == 200
                assert await response.text() == "REGISTERED"
    finally:
        context.destroy()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_server_lossless_rule_overrides_local_delay(monkeypatch, tmp_path):
    rule = lossless_rule(enable=False)
    stub = RegisterStub(rules=[rule])
    context = make_context(
        monkeypatch, tmp_path, stub, strategy="DELAY_BY_TIME", delayRegisterInterval="10s",
    )
    provider = ProviderAPI(context)
    try:
        await provider.async_lossless_register(instance_request())
        assert any(call[0] == "RegisterInstance" for call in stub.calls)
        assert context.engine.lossless_manager.check_register_status() == RegisterStatus.REGISTERED
    finally:
        context.destroy()


def _discovery_instance(instance_id, ctime, weight=100):
    return service_pb2.Instance(
        id={"value": instance_id},
        host={"value": "127.0.0.1"},
        port={"value": 8080},
        weight={"value": weight},
        healthy={"value": True},
        ctime={"value": ctime},
    )


async def _wait_for_rules(context):
    manager = context.engine.lossless_manager
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and ("ns", "svc") not in manager._rules_cache:
        await asyncio.sleep(0.01)
    assert ("ns", "svc") in manager._rules_cache


async def _wait_for_instance_ids(consumer, query, expected):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        instances = (await consumer.async_get_all_instances(query)).get_instances()
        if [instance.get_id() for instance in instances] == expected:
            return instances
        await asyncio.sleep(0.01)
    instances = (await consumer.async_get_all_instances(query)).get_instances()
    assert [instance.get_id() for instance in instances] == expected


@pytest.mark.asyncio
async def test_consumer_fetches_rules_and_applies_warmup(monkeypatch, tmp_path):
    old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    new_time = datetime.now(timezone.utc).isoformat()
    stub = RegisterStub(
        rules=[_warmup_rule(interval=300, curvature=1)],
        instances=[
            _discovery_instance("old", old_time),
            _discovery_instance("new", new_time),
        ],
    )
    context = make_context(monkeypatch, tmp_path, stub, provider=False, consumer=True)
    consumer = ConsumerAPI(context)
    query = GetOneInstanceRequest(namespace="ns", service="svc")
    try:
        await consumer.async_get_one_instance(query)
        await _wait_for_rules(context)

        counts = {"old": 0, "new": 0}
        for _ in range(500):
            selected = await consumer.async_get_one_instance(query)
            counts[selected.get_id()] += 1
        assert counts["old"] > 450
        assert counts["new"] < 50
    finally:
        context.destroy()


@pytest.mark.asyncio
async def test_consumer_overload_protection_disables_warmup(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    stub = RegisterStub(
        rules=[_warmup_rule(interval=300, curvature=1, overload=True, threshold=50)],
        instances=[
            _discovery_instance("first", now),
            _discovery_instance("second", now),
        ],
    )
    context = make_context(monkeypatch, tmp_path, stub, provider=False, consumer=True)
    consumer = ConsumerAPI(context)
    query = GetOneInstanceRequest(namespace="ns", service="svc")
    try:
        await consumer.async_get_one_instance(query)
        await _wait_for_rules(context)

        counts = {"first": 0, "second": 0}
        for _ in range(500):
            selected = await consumer.async_get_one_instance(query)
            counts[selected.get_id()] += 1
        assert 50 < counts["first"] < 450
        assert 50 < counts["second"] < 450
    finally:
        context.destroy()


@pytest.mark.asyncio
async def test_provider_offline_updates_consumer_discovery(monkeypatch, tmp_path):
    stub = RegisterStub()
    provider_context = make_context(monkeypatch, tmp_path, stub, delayRegisterInterval="10ms")
    consumer_context = make_context(monkeypatch, tmp_path, stub, provider=False, consumer=True)
    provider = ProviderAPI(provider_context)
    consumer = ConsumerAPI(consumer_context)
    request = instance_request()
    query = GetInstancesRequest(namespace="ns", service="svc")

    try:
        await _wait_for_instance_ids(consumer, query, [])

        await provider.async_lossless_register(request)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not any(call[0] == "RegisterInstance" for call in stub.calls):
            await asyncio.sleep(0.01)
        assert any(call[0] == "RegisterInstance" for call in stub.calls)

        await _wait_for_instance_ids(consumer, query, ["registered"])

        await provider.async_lossless_deregister(request)
        assert any(call[0] == "DeregisterInstance" for call in stub.calls)
        await _wait_for_instance_ids(consumer, query, [])
    finally:
        provider_context.destroy()
        consumer_context.destroy()
