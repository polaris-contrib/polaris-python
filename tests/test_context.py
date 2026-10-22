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

"""Multi-context integration using real plugins and an in-process gRPC boundary."""

import asyncio
import copy
import inspect
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from google.protobuf import json_format
from polarismesh_specification.api.v1.service_manage import client_pb2, response_pb2, service_pb2

from polaris import Configuration, ConsumerAPI, LogOptions, ProviderAPI, SDKError, init_context_by_config
from polaris.api import log
from polaris.pkg.model.context import ContextKeyEngine
from polaris.pkg.model.core import EventType as ModelEventType, ServiceEventKey
from polaris.pkg.model.server import InstanceDiscoverRequest, InstanceRegisterRequest
from polaris.pkg.model.service import GetInstancesRequest
from polaris.pkg.model import util
from polaris.plugin.local_registry.file_cache import LocalFileCache
from polaris.plugin.local_registry.local_cache import InstanceFilter
from polaris.plugin.server_connector.grpc_connector import connection
from polaris.plugin.service_router.base import NearbyKeyAreaWithRegion
from polaris.plugin_manager import DefaultPluginManager, EventType, PluginType


class FakeChannel:
    """Track per-context channel creation and closure without network access."""

    def __init__(self, address):
        self.address = address
        self.closed = False
        self.owner = asyncio.get_running_loop()

    async def close(self):
        assert asyncio.get_running_loop() is self.owner
        self.closed = True


class FakeStub:
    """Expose independent server snapshots and capture requests sent by the real transport."""

    def __init__(self, channel):
        self.channel = channel
        self.calls = []
        self.reported = threading.Event()
        self.heartbeat_received = threading.Event()

    def record(self, method, request, metadata):
        self.calls.append((method, copy.deepcopy(request), dict(metadata), asyncio.get_running_loop()))

    async def ReportClient(self, request, timeout=None, metadata=()):
        self.record("report", request, metadata)
        self.reported.set()
        return response_pb2.Response(code={"value": 200000}, client=client_pb2.Client(
            location={"region": {"value": self.channel.address}}))

    async def RegisterInstance(self, request, timeout=None, metadata=()):
        self.record("register", request, metadata)
        return response_pb2.Response(code={"value": 200000}, instance=service_pb2.Instance(
            id={"value": self.channel.address}))

    async def Heartbeat(self, request, timeout=None, metadata=()):
        self.record("heartbeat", request, metadata)
        self.heartbeat_received.set()
        return response_pb2.Response(code={"value": 200000})

    def Discover(self, requests, timeout=None, metadata=()):
        async def responses():
            async for request in requests:
                self.record("discover", request, metadata)
                response = response_pb2.DiscoverResponse(code={"value": 200000}, type=request.type,
                    service=service_pb2.Service(name=request.service.name, namespace=request.service.namespace,
                                               revision={"value": self.channel.address}))
                if request.type == 1:
                    response.instances.append(service_pb2.Instance(
                        id={"value": self.channel.address}, host={"value": "127.0.0.1"},
                        service=request.service.name, namespace=request.service.namespace,
                        port={"value": 8080}, healthy={"value": True}, weight={"value": 100}))
                elif request.type == 3:
                    response.routing.revision.value = self.channel.address
                yield response
        return responses()


@pytest.fixture
def contexts(monkeypatch, tmp_path):
    clients = []
    channels = []
    stubs = []

    def create_channel(address):
        channel = FakeChannel(address)
        channels.append(channel)
        return channel

    def create_stub(channel):
        stub = FakeStub(channel)
        stubs.append(stub)
        return stub

    monkeypatch.setattr(connection.grpc.aio, "insecure_channel", create_channel)
    monkeypatch.setattr(connection.grpcapi_pb2_grpc, "PolarisGRPCStub", create_stub)

    async def no_tcp_connection(host, port):
        raise OSError("offline TCP boundary")

    monkeypatch.setattr(util.asyncio, "open_connection", no_tcp_connection)

    def create(name, config=None, options=None):
        if config is None:
            config = Configuration()
            config.set_default()
            config.get_global().get_server_connector().addresses = [f"{name}:8091"]
            config.get_global().get_server_connector().token = name
            config.get_global().get_api().bind_ip = "127.0.0.1"
            config.get_consumer().get_local_cache().persist_dir = str(tmp_path / name / "cache")
        client = init_context_by_config(config, log_options=options or LogOptions(
            level="debug", file_path=tmp_path / name / "client.log"))
        clients.append(client)
        return client

    create.channels = channels
    create.stubs = stubs
    try:
        yield create
    finally:
        for client in reversed(clients):
            client.destroy()
            assert not client.get_engine().thread.is_alive()
            assert not client.get_engine().file_cache.write_thread.is_alive()
            assert all(instance.handler.stream is None
                       for instance in client.get_value_context().logger._categories.values())


def discover(client, service="svc"):
    result = ConsumerAPI(client).get_instances(GetInstancesRequest(namespace="ns", service=service))
    return result.get_instances()[0]


def test_contexts_have_private_plugins_subscribers_loops_and_identity(contexts):
    first, second = contexts("first"), contexts("second")
    assert first.get_client_id() != second.get_client_id()
    assert first.get_engine().global_ctx is first.get_value_context()
    assert first.get_plugins() is not second.get_plugins()
    assert first.get_engine().loop is not second.get_engine().loop
    assert first.get_value_context().get_value(ContextKeyEngine) is first.get_engine()
    for typ, plugins in first.get_plugins().plugin_instance.items():
        for name, instance in plugins.items():
            assert instance is not second.get_plugins().get_instance(typ, name)
    for client in (first, second):
        handlers = client.get_plugins().get_event_subscriber(EventType.ON_LOCALVALUE_CREATED)
        assert handlers == (client.get_plugins().get_instance(PluginType.CIRCUIT_BREAKER, "composite"),)
    assert DefaultPluginManager.plugin_instance == {}
    assert DefaultPluginManager.event_handle_map == {}


def test_context_reports_stable_unique_client_id_with_its_own_token(contexts):
    first, second = contexts("first"), contexts("second")
    for client in (first, second):
        engine = client.get_engine()
        engine._run_sync(engine.do_period_client_report(type(client.get_value_context())()))
    reports = [call for stub in contexts.stubs for call in stub.calls if call[0] == "report"]
    for client, name in ((first, "first"), (second, "second")):
        own_reports = [call for call in reports if call[2]["x-polaris-token"] == name]
        assert own_reports
        assert all(call[1].id.value == client.get_client_id() for call in own_reports)
        assert all(call[1].type == client_pb2.Client.SDK for call in own_reports)
        assert all(call[3] is client.get_engine().loop for call in own_reports)
        assert client.get_value_context().get_value(NearbyKeyAreaWithRegion) == f"{name}:8091"


def test_context_resolves_sdk_ip_on_owner_loop_before_reporting(contexts, monkeypatch, tmp_path):
    config = Configuration()
    config.set_default()
    connector = config.get_global().get_server_connector()
    connector.addresses = ["first:8091", "second:8092"]
    connector.connect_timeout = 750
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "cache")
    probes = []

    async def probe(address, timeout):
        probes.append((address, timeout, asyncio.get_running_loop()))
        return "192.0.2.1"

    monkeypatch.setattr(util, "get_local_ip", probe)
    client = contexts("auto", config)
    assert probes == [("first:8091", 750, client.get_engine().loop)]
    assert client.get_config().get_global().get_api().get_bind_ip() == "192.0.2.1"
    assert client.get_config().get_global().get_api().bind_ip == ""
    assert config.get_global().get_api().get_bind_ip() == ""
    client.get_engine()._run_sync(client.get_engine().do_period_client_report(type(client.value_context)()))
    reports = [call[1] for stub in contexts.stubs for call in stub.calls if call[0] == "report"]
    assert reports and all(report.host.value == "192.0.2.1" for report in reports)


@pytest.mark.parametrize("error", [OSError("unreachable"), TimeoutError("timeout"), ValueError("bad address")])
def test_context_ip_probe_failure_warns_without_stopping_startup(contexts, monkeypatch, tmp_path, error):
    async def probe(address, timeout):
        raise error

    monkeypatch.setattr(util, "get_local_ip", probe)
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = ["offline:8091"]
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "cache")
    client = contexts("offline", config)
    assert client.get_config().get_global().get_api().get_bind_ip() == ""
    assert not client.is_destroy()
    client.get_engine()._run_sync(client.get_engine().do_period_client_report(type(client.value_context)()))
    reports = [call[1] for stub in contexts.stubs for call in stub.calls if call[0] == "report"]
    assert reports and all(report.host.value == "" for report in reports)
    assert "failed to resolve SDK bindIP via offline:8091; keeping it empty" in (
        client.get_value_context().logger.get_logger("network").file_path.read_text())
    assert "failed to resolve SDK bindIP" not in client.get_value_context().logger.file_path.read_text()


@pytest.mark.parametrize("use_interface", [False, True])
def test_context_skips_auto_probe_for_explicit_ip_or_interface(contexts, monkeypatch, tmp_path, use_interface):
    async def probe(address, timeout):
        raise AssertionError("explicit address must not probe")

    monkeypatch.setattr(util, "get_local_ip", probe)
    monkeypatch.setattr(util, "get_ip", lambda name: "192.0.2.1")
    config = Configuration()
    config.set_default()
    api = config.get_global().get_api()
    if use_interface:
        api.bind_intf = "test0"
    else:
        api.bind_ip = "192.0.2.1"
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "cache")
    client = contexts("explicit", config)
    assert client.get_config().get_global().get_api().get_bind_ip() == "192.0.2.1"


def test_unexpected_ip_resolver_error_releases_startup_resources(contexts, monkeypatch, tmp_path):
    async def probe(address, timeout):
        raise RuntimeError("unexpected resolver failure")

    monkeypatch.setattr(util, "get_local_ip", probe)
    config = Configuration()
    config.set_default()
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "cache")
    with pytest.raises(RuntimeError, match="unexpected resolver failure"):
        contexts("failed", config)
    assert not contexts.channels
    assert not contexts.stubs
    assert not log._context_log_files


def test_same_input_config_resolves_private_ips_per_context(contexts, monkeypatch, tmp_path):
    config = Configuration()
    config.set_default()
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "cache")
    addresses = iter(["192.0.2.1", "192.0.2.2"])

    async def probe(address, timeout):
        return next(addresses)

    monkeypatch.setattr(util, "get_local_ip", probe)
    first, second = contexts("first", config), contexts("second", config)
    assert first.get_config().get_global().get_api().get_bind_ip() == "192.0.2.1"
    assert second.get_config().get_global().get_api().get_bind_ip() == "192.0.2.2"
    assert config.get_global().get_api().get_bind_ip() == ""
    first.destroy()
    second.get_engine()._run_sync(second.get_engine().do_period_client_report(type(second.value_context)()))
    assert second.get_config().get_global().get_api().get_bind_ip() == "192.0.2.2"


@pytest.mark.parametrize("automatic", [False, True])
def test_resolved_sdk_ip_does_not_replace_registration_host(contexts, monkeypatch, tmp_path, automatic):
    async def probe(address, timeout):
        return "192.0.2.1"

    monkeypatch.setattr(util, "get_local_ip", probe)
    config = Configuration()
    config.set_default()
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "cache")
    client = contexts("provider", config)
    provider = ProviderAPI(client)
    register = provider.register_instance if automatic else provider.register
    request = InstanceRegisterRequest("svc", "token", "ns", "198.51.100.1", 8080)
    register(request)
    assert request.host == "198.51.100.1"
    registrations = [call[1] for stub in contexts.stubs for call in stub.calls if call[0] == "register"]
    assert len(registrations) == 1
    assert registrations[0].host.value == "198.51.100.1"
    with pytest.raises(SDKError, match="host should not be empty"):
        register(InstanceRegisterRequest("svc", "token", "ns", "", 8080))
    assert sum(call[0] == "register" for stub in contexts.stubs for call in stub.calls) == 1


def test_contexts_keep_independent_discovery_snapshots_and_rules(contexts):
    first, second = contexts("first"), contexts("second")
    first_node, second_node = discover(first), discover(second)
    assert first_node.get_id() == "first:8091"
    assert second_node.get_id() == "second:8091"
    first_node.get_circuit_breaker_status().allowed_requests_after_half_open = 42
    assert second_node.get_circuit_breaker_status().allowed_requests_after_half_open != 42
    key = ServiceEventKey("ns", "svc", ModelEventType.Instance)
    one = first.get_engine().registry.service_map[key].value
    two = second.get_engine().registry.service_map[key].value
    assert one is not two
    assert one.revision == "first:8091"
    assert two.revision == "second:8091"


def test_idle_expiry_reclaims_only_its_context_and_allows_sync_reload(contexts):
    first, second = contexts("first"), contexts("second")
    discover(first)
    discover(second)
    one, two = first.get_engine(), second.get_engine()
    original = one.registry.service_map.copy()

    async def evict():
        for obj in one.registry.service_map.values():
            obj.last_visit_time -= 2 * 24 * 60 * 60
        return await one.registry.expire_services()

    assert set(one._run_sync(evict())) == set(original)
    assert one.registry.service_map == one.registry.get_services() == one.update_task_set == {}
    assert one.svc_connector._streams == one.svc_connector._stream_locks == {}
    assert not one.svc_connector.connection._closed
    assert len(two.registry.service_map) == len(two.update_task_set) == len(two.svc_connector._streams) == 1
    assert discover(second).get_id() == "second:8091"
    assert discover(first).get_id() == "first:8091"
    assert all(one.registry.service_map[key] is not value for key, value in original.items())
    assert set(one.update_task_set) == set(original)


def test_idle_expiry_deletes_shared_backups_but_preserves_other_context_memory(contexts, tmp_path):
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = ["shared:8091"]
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "shared")
    first, second = contexts("first", config), contexts("second", config)
    discover(first)
    discover(second)
    one, two = first.get_engine(), second.get_engine()
    one.file_cache.queue.join()
    two.file_cache.queue.join()
    requests = [InstanceDiscoverRequest(1, "svc", "ns")]
    before = {request.type: two.file_cache.get(request) for request in requests}
    assert all(response is not None for response in before.values())

    async def evict():
        for obj in one.registry.service_map.values():
            obj.last_visit_time -= 2 * 24 * 60 * 60
        assert len(await one.registry.expire_services()) == 1

    one._run_sync(evict())
    one.file_cache.queue.join()
    for request in requests:
        assert two.file_cache.get(request) is None
        assert not Path(one.file_cache.get_cache_file_path(request)).exists()
    assert discover(second).get_id() == "shared:8091"
    assert len(two.registry.service_map) == 1
    assert one.registry.service_map == one.update_task_set == one.svc_connector._streams == {}


@pytest.mark.asyncio
async def test_offline_restart_refreshes_all_backups_after_server_recovery(contexts, tmp_path, monkeypatch):
    initial = contexts("first")
    await ConsumerAPI(initial).async_get_instances(GetInstancesRequest(namespace="ns", service="svc"))
    initial.get_engine().file_cache.queue.join()
    config = initial.get_config()
    initial.destroy()
    config.get_global().get_server_connector().addresses = ["recovered:8091"]
    config.get_global().get_api().timeout = 20
    for path in Path(config.get_consumer().get_local_cache().persist_dir).glob("svc#ns#svc#*.json"):
        os.utime(path, (time.time() - 120, time.time() - 120))
    restarted = contexts("restart", config)
    engine = restarted.get_engine()
    original = engine.svc_connector.connection._stub
    remote_ready = False
    failures = []

    # Exercise actual reconnecting streams, replacing only channel/server boundaries.
    class OfflineStub:
        async def ReportClient(self, request, timeout=None, metadata=()):
            return response_pb2.Response(code={"value": 200000})

        def Discover(self, requests, timeout=None, metadata=()):
            async def responses():
                async for request in requests:
                    failures.append(request.type)
                    raise connection.grpc.aio.AioRpcError(connection.grpc.StatusCode.UNAVAILABLE, (), (), "offline")
                    yield
            return responses()

    async def network_stub(address):
        if not remote_ready:
            return OfflineStub()
        return await original(address)

    monkeypatch.setattr(engine.svc_connector.connection, "_stub", network_stub)
    fallback = await ConsumerAPI(restarted).async_get_instances(GetInstancesRequest(namespace="ns", service="svc"))
    assert fallback.is_loaded_from_file()
    assert fallback.get_revision() == "first:8091"
    hidden = engine.registry.service_map[ServiceEventKey("ns", "svc", ModelEventType.Instance)]
    assert failures == [1]
    assert hidden.is_remote_updated() is False
    assert hidden.value.get_revision() == "first:8091"
    assert engine.registry.get_instances(InstanceFilter("ns", "svc", False)) is None
    assert engine.svc_connector._streams == {}
    remote_ready = True

    async def wait_for_periodic_refresh():
        while any(obj.value is None or obj.value.get_revision() != "recovered:8091"
                  for obj in engine.registry.service_map.values()):
            await asyncio.sleep(0.01)

    await asyncio.wait_for(engine._run_async(wait_for_periodic_refresh()), 5)
    await asyncio.to_thread(engine.file_cache.queue.join)
    result = await ConsumerAPI(restarted).async_get_instances(GetInstancesRequest(namespace="ns", service="svc"))
    assert result.get_instances()[0].get_id() == "recovered:8091"
    response = engine.file_cache.get(InstanceDiscoverRequest(1, "svc", "ns"))
    assert response.service.revision.value == "recovered:8091"
    restarted.destroy()
    assert all(not thread.is_alive() for thread in engine.file_cache._read_executor._threads)


def test_background_refresh_does_not_renew_idle_clock(contexts):
    client = contexts("first")
    discover(client)
    engine = client.get_engine()

    async def refresh():
        task = next(iter(engine.update_task_set.values()))
        task.cache_obj.last_visit_time -= 2 * 24 * 60 * 60
        last_visit = task.cache_obj.last_visit_time
        task.last_update_time = 0
        await engine.process_update_task(task)
        assert task.cache_obj.last_visit_time == last_visit
        assert await engine.registry.expire_services() == [task.service_key]

    engine._run_sync(refresh())


@pytest.mark.asyncio
async def test_expiry_cancels_blocked_refresh_without_stalling_other_resources(contexts, monkeypatch):
    client = contexts("first")
    await ConsumerAPI(client).async_get_instances(GetInstancesRequest(namespace="ns", service="svc"))
    engine = client.get_engine()
    entered, stopped = threading.Event(), threading.Event()
    original = FakeStub.Discover

    def blocking_discover(stub, requests, timeout=None, metadata=()):
        async def responses():
            try:
                async for request in requests:
                    stub.record("discover", request, metadata)
                    entered.set()
                    await asyncio.sleep(60)
                    yield response_pb2.DiscoverResponse()
            finally:
                stopped.set()
        return responses()

    monkeypatch.setattr(FakeStub, "Discover", blocking_discover)
    key = ServiceEventKey("ns", "svc", ModelEventType.Instance)

    async def start_refresh():
        await engine.svc_connector.stop_discover(InstanceDiscoverRequest(1, "svc", "ns"))
        task = engine.update_task_set[key]
        task.last_update_time = 0
        task.runner = asyncio.create_task(engine._run_service_update_task(task))
        return task.runner

    runner = await engine._run_async(start_refresh())
    assert await asyncio.to_thread(entered.wait, 3)
    monkeypatch.setattr(FakeStub, "Discover", original)
    # A blocked refresh must not prevent another service's public async discovery.
    result = await ConsumerAPI(client).async_get_instances(GetInstancesRequest(namespace="ns", service="other"))
    assert result.get_instances()[0].get_id() == "first:8091"

    async def evict():
        for resource, obj in engine.registry.service_map.items():
            if resource.service == "svc":
                obj.last_visit_time -= 2 * 24 * 60 * 60
        return await engine.registry.expire_services()

    expired = await asyncio.wait_for(engine._run_async(evict()), 3)
    assert len(expired) == 1
    assert runner.cancelled()
    assert stopped.is_set()
    assert all(resource.service == "other" for resource in engine.registry.service_map)
    assert len(engine.svc_connector._streams) == 1
    result = await ConsumerAPI(client).async_get_instances(GetInstancesRequest(namespace="ns", service="svc"))
    assert result.get_instances()[0].get_id() == "first:8091"


@pytest.mark.asyncio
async def test_stale_refresh_response_cannot_update_reloaded_resource_or_backup(contexts, monkeypatch):
    client = contexts("first")
    await ConsumerAPI(client).async_get_instances(GetInstancesRequest(namespace="ns", service="svc"))
    engine = client.get_engine()
    entered, release = threading.Event(), threading.Event()
    original_discover = engine.svc_connector.discover
    saved = []

    async def late_response(request, use_discover_cache=True):
        entered.set()
        await asyncio.to_thread(release.wait, 3)
        return response_pb2.DiscoverResponse(code={"value": 200000},
            service=service_pb2.Service(revision={"value": "obsolete"}))

    monkeypatch.setattr(engine.svc_connector, "discover", late_response)
    monkeypatch.setattr(engine.file_cache, "save", lambda request, response: saved.append(response))
    key = ServiceEventKey("ns", "svc", ModelEventType.Instance)

    async def start_refresh():
        task = engine.update_task_set[key]
        task.last_update_time = 0
        # Deliberately leave this old reader untracked to exercise the generation check.
        return asyncio.create_task(engine.process_update_task(task))

    pending = await engine._run_async(start_refresh())
    assert await asyncio.to_thread(entered.wait, 3)

    async def evict():
        engine.registry.service_map[key].last_visit_time -= 2 * 24 * 60 * 60
        assert await engine.registry.expire_services() == [key]

    await engine._run_async(evict())
    monkeypatch.setattr(engine.svc_connector, "discover", original_discover)
    await ConsumerAPI(client).async_get_instances(GetInstancesRequest(namespace="ns", service="svc"))
    expected_writes = len(saved)
    release.set()

    async def wait_refresh():
        await pending

    await engine._run_async(wait_refresh())
    assert engine.registry.service_map[key].value.revision == "first:8091"
    assert len(saved) == expected_writes


@pytest.mark.asyncio
async def test_periodic_expiry_runs_on_owner_loop_and_stops_on_destroy(contexts):
    config = Configuration()
    config.set_default()
    config.get_consumer().get_local_cache().service_expire_time = 5000
    client = contexts("periodic", config)
    await ConsumerAPI(client).async_get_instances(GetInstancesRequest(namespace="ns", service="svc"))
    engine = client.get_engine()
    original = engine.registry.service_map.copy()

    async def make_idle():
        for obj in original.values():
            obj.last_visit_time -= 10

    await engine._run_async(make_idle())

    async def wait_expiry():
        while engine.registry.service_map:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(engine._run_async(wait_expiry()), 4)
    assert engine.svc_connector._streams == engine.update_task_set == {}
    assert all(obj.invalid for obj in original.values())
    client.destroy()
    assert engine.loop is None
    assert not engine.thread.is_alive()


def test_same_configuration_creates_private_snapshots(contexts, tmp_path):
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = ["shared:8091"]
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "shared")
    first, second = contexts("first", config), contexts("second", config)
    assert first.get_config() is not config
    assert first.get_config() is not second.get_config()
    config.get_global().get_server_connector().addresses.append("changed:8091")
    first.get_config().get_global().get_server_connector().token = "changed"
    assert second.get_config().get_global().get_server_connector().addresses == ["shared:8091"]
    assert second.get_config().get_global().get_server_connector().token == ""
    assert first.get_engine().svc_connector.connection.settings.token == ""


def test_same_endpoint_has_independent_channels_and_discovery_streams(contexts, tmp_path):
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = ["shared:8091"]
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "first" / "cache")
    first = contexts("first", config)
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "second" / "cache")
    second = contexts("second", config)
    discover(first)
    discover(second)
    first_connection = first.get_engine().svc_connector.connection
    second_connection = second.get_engine().svc_connector.connection
    assert first_connection._channels["shared:8091"] is not second_connection._channels["shared:8091"]
    assert first_connection._stubs["shared:8091"] is not second_connection._stubs["shared:8091"]
    first_streams = first.get_engine().svc_connector._streams
    second_streams = second.get_engine().svc_connector._streams
    assert first_streams.keys() == second_streams.keys()
    assert first_streams
    assert all(first_streams[key] is not second_streams[key] for key in first_streams)
    first.destroy()
    assert not second_connection._closed
    assert discover(second, "after-destroy").get_id() == "shared:8091"


def test_plugin_event_callbacks_are_dispatched_only_to_own_context(contexts, monkeypatch):
    first, second = contexts("first"), contexts("second")
    calls = {first.get_client_id(): [], second.get_client_id(): []}
    for client in (first, second):
        handler = client.get_plugins().get_instance(PluginType.CIRCUIT_BREAKER, "composite")
        original = handler.on_plugin_event

        def capture(event, value, original=original, client_id=client.get_client_id()):
            calls[client_id].append((event, value))
            return original(event, value)

        monkeypatch.setattr(handler, "on_plugin_event", capture)
    discover(first)
    assert len(calls[first.get_client_id()]) == 1
    assert calls[second.get_client_id()] == []
    discover(second)
    assert len(calls[second.get_client_id()]) == 1
    first.destroy()
    discover(second, "after-destroy")
    assert len(calls[first.get_client_id()]) == 1
    assert len(calls[second.get_client_id()]) == 2


def test_contexts_initialize_concurrently_without_replacing_plugins(contexts):
    with ThreadPoolExecutor(max_workers=4) as pool:
        clients = list(pool.map(contexts, ["one", "two", "three", "four"]))
    assert len({client.get_client_id() for client in clients}) == 4
    assert len({id(client.get_plugins()) for client in clients}) == 4
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(discover, clients))
    assert [node.get_id() for node in results] == ["one:8091", "two:8091", "three:8091", "four:8091"]


@pytest.mark.asyncio
async def test_destroying_one_context_preserves_another_heartbeat_and_discovery(contexts):
    first, second = contexts("first"), contexts("second")
    for client in (first, second):
        request = InstanceRegisterRequest("svc", "service-token", "ns", "127.0.0.1", 8080, ttl=1)
        await ProviderAPI(client).async_register_instance(request)
    first_stub = next(stub for stub in contexts.stubs if stub.channel.address == "first:8091")
    second_stub = next(stub for stub in contexts.stubs if stub.channel.address == "second:8091")
    assert await asyncio.to_thread(first_stub.heartbeat_received.wait, 3)
    assert await asyncio.to_thread(second_stub.heartbeat_received.wait, 3)
    first.destroy()
    previous = len(first_stub.calls)
    second_stub.heartbeat_received.clear()
    assert await asyncio.to_thread(second_stub.heartbeat_received.wait, 3)
    result = await ConsumerAPI(second).async_get_instances(GetInstancesRequest(namespace="ns", service="svc"))
    assert result.get_instances()[0].get_id() == "second:8091"
    assert len(first_stub.calls) == previous
    assert first.get_plugins().plugin_instance == {}
    assert first.get_plugins().event_handle_map == {}
    assert not second.is_destroy()
    assert not second.get_engine().svc_connector.connection._closed
    assert second.get_engine().file_cache.write_thread.is_alive()
    assert second.get_engine().register_states._states
    with pytest.raises(SDKError, match="destroyed"):
        await ConsumerAPI(first).async_get_instances(GetInstancesRequest(namespace="ns", service="svc"))


def test_context_log_files_and_levels_are_independent(contexts, monkeypatch, tmp_path):
    monkeypatch.setenv("POLARIS_LOG_PATH", str(tmp_path / "logs" / "polaris.log"))
    first = contexts("first", options=LogOptions(level="debug"))
    second = contexts("second", options=LogOptions(level="error"))
    async def emit():
        log.debug("private-debug")
        log.error("private-error")
    for client in (first, second):
        client.get_engine()._run_sync(emit())
    one, two = first.get_value_context().logger, second.get_value_context().logger
    assert one.file_path != two.file_path
    assert one.logger.level == logging.DEBUG
    assert two.logger.level == logging.ERROR
    assert "private-debug" in one.file_path.read_text()
    assert "private-debug" not in two.file_path.read_text()
    assert first.get_client_id() not in two.file_path.read_text()
    monkeypatch.setattr(log, "default_logger", logging.Logger("unrelated"))
    first.destroy()
    second.get_engine()._run_sync(emit())
    assert one.handler.stream is None
    assert two.handler.stream is not None
    assert "private-error" in two.file_path.read_text()


def test_context_plugins_use_their_category_logs_and_close_all_handlers(contexts, tmp_path):
    first = contexts("first", options=LogOptions(level="debug", log_dir=tmp_path / "logs"))
    second = contexts("second", options=LogOptions(level="debug", log_dir=tmp_path / "logs"))
    for client in (first, second):
        engine = client.get_engine()
        context_log = client.get_value_context().logger
        network = context_log.get_logger("network")
        cache = context_log.get_logger("cache")
        assert engine.svc_connector.connection.logger is network
        assert engine.file_cache.logger is cache
        assert network.file_path == tmp_path / "logs" / "network" / f"polaris-network-{client.get_client_id()}.log"
        assert discover(client).get_id().endswith(":8091")
        engine.file_cache.queue.join()
        assert "success to back up data" in cache.file_path.read_text()
        assert "success to back up data" not in context_log.file_path.read_text()
        network.info("network-only-%s", client.get_client_id())
        assert "network-only" not in context_log.file_path.read_text()
    first.destroy()
    first_log, second_log = first.get_value_context().logger, second.get_value_context().logger
    assert all(instance.handler.stream is None for instance in first_log._categories.values())
    assert all(instance.handler.stream is not None for instance in second_log._categories.values())
    assert first.get_client_id() not in second_log.get_logger("network").file_path.read_text()
    assert discover(second).get_id() == "second:8091"


def test_context_disk_queues_use_configured_independent_directories(contexts):
    first, second = contexts("first"), contexts("second")
    discover(first)
    discover(second)
    for client, expected in ((first, "first:8091"), (second, "second:8091")):
        cache = client.get_engine().file_cache
        assert cache is client.get_plugins().get_instance(PluginType.LOCAL_CACHE, "file")
        cache.queue.join()
        response = json_format.Parse(
            (Path(cache.base_dir) / "svc#ns#svc#instance.json").read_text(encoding="utf-8"),
            response_pb2.DiscoverResponse(),
        )
        assert response.service.revision.value == expected


def test_failed_context_initialization_releases_its_resources_without_affecting_existing(
    contexts, monkeypatch, tmp_path,
):
    existing = contexts("existing")
    created = []

    def track_file_cache(init_ctx):
        cache = LocalFileCache(init_ctx)
        created.append((cache, init_ctx.logger))
        return cache

    monkeypatch.setitem(DefaultPluginManager.plugin_container[PluginType.LOCAL_CACHE], "file", track_file_cache)
    config = Configuration()
    config.set_default()
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "failed")
    config.get_consumer().get_load_balancer().type = "missing"
    with pytest.raises(SDKError, match="Plugin is not available"):
        contexts("failed", config)
    cache, failed_log = created[0]
    assert not cache.write_thread.is_alive()
    assert cache.lock_file.closed
    assert failed_log.handler.stream is None
    assert all(instance.handler.stream is None for instance in failed_log._categories.values())
    assert discover(existing).get_id() == "existing:8091"


def test_plugin_constructor_failure_cleans_partial_setup(contexts, monkeypatch):
    created = []

    def track_file_cache(init_ctx):
        cache = LocalFileCache(init_ctx)
        created.append((cache, init_ctx.logger))
        return cache

    def failing_plugin(init_ctx):
        raise SDKError(1, "constructor failure")

    monkeypatch.setitem(DefaultPluginManager.plugin_container[PluginType.LOCAL_CACHE], "file", track_file_cache)
    monkeypatch.setitem(DefaultPluginManager.plugin_container[PluginType.LOCAL_CACHE], "failing", failing_plugin)
    with pytest.raises(SDKError, match="constructor failure"):
        contexts("failed")
    cache, failed_log = created[0]
    assert not cache.write_thread.is_alive()
    assert cache.lock_file.closed
    assert failed_log.handler.stream is None
    assert all(instance.handler.stream is None for instance in failed_log._categories.values())


@pytest.mark.asyncio
async def test_owner_loop_destroy_releases_resources_after_tasks_stop(contexts):
    client = contexts("first")
    engine = client.get_engine()
    completed = threading.Event()
    async def stop():
        client.destroy()
        completed.set()
    asyncio.run_coroutine_threadsafe(stop(), engine.loop)
    assert await asyncio.to_thread(completed.wait, 3)
    await asyncio.to_thread(engine.thread.join, 3)
    assert not engine.thread.is_alive()
    assert not engine.file_cache.write_thread.is_alive()
    assert client.get_plugins().plugin_instance == {}
    assert client.get_value_context().logger.handler.stream is None


def test_destroy_closes_channels_and_is_idempotent(contexts):
    client = contexts("first")
    discover(client)
    channels = [channel for channel in contexts.channels if channel.address == "first:8091"]
    assert len(channels) == 1
    client.destroy()
    client.destroy()
    assert channels[0].closed
    assert client.get_engine().loop is None


@pytest.mark.asyncio
async def test_cancelled_submission_closes_coroutine_before_owner_loop_runs_it(contexts):
    client = contexts("first")
    engine = client.get_engine()
    blocked, release = threading.Event(), threading.Event()

    def block_owner():
        blocked.set()
        release.wait(3)

    engine.loop.call_soon_threadsafe(block_owner)
    assert await asyncio.to_thread(blocked.wait, 3)
    coroutine = asyncio.sleep(10)
    try:
        caller = asyncio.create_task(engine._run_async(coroutine))
        await asyncio.sleep(0)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
    finally:
        release.set()
    await engine._run_async(asyncio.sleep(0))
    assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED


def test_creating_and_destroying_context_preserves_application_logging(contexts, monkeypatch):
    application_logger = logging.Logger("application")
    handler = logging.NullHandler()
    application_logger.addHandler(handler)
    application_logger.setLevel(logging.WARNING)
    monkeypatch.setattr(log, "default_logger", application_logger)
    client = contexts("first")
    client.destroy()
    assert log.default_logger is application_logger
    assert application_logger.handlers == [handler]
    assert application_logger.level == logging.WARNING
    assert not handler._closed


def test_context_captures_code_assigned_log_options_without_hot_updates(contexts, tmp_path):
    options = LogOptions()
    options.level = "debug"
    options.file_path = tmp_path / "first.log"
    options.max_bytes = 4096
    options.backup_count = 2
    first = contexts("first", options=options)
    options.level = "error"
    options.file_path = tmp_path / "second.log"
    options.max_bytes = 8192
    options.backup_count = 3
    second = contexts("second", options=options)
    one, two = first.get_value_context().logger, second.get_value_context().logger
    assert one.logger.level == logging.DEBUG
    assert one.file_path == tmp_path / "first.log"
    assert one.handler.maxBytes == 4096
    assert one.handler.backupCount == 2
    assert two.logger.level == logging.ERROR
    assert two.file_path == tmp_path / "second.log"
    assert two.handler.maxBytes == 8192
    assert two.handler.backupCount == 3


@pytest.mark.asyncio
async def test_destroy_cancels_inflight_discovery_and_closes_its_stream(contexts, monkeypatch):
    first, second = contexts("first"), contexts("second")
    entered, stopped = threading.Event(), threading.Event()
    original = FakeStub.Discover

    def blocking_discover(stub, requests, timeout=None, metadata=()):
        if stub.channel.address != "first:8091":
            return original(stub, requests, timeout, metadata)

        async def responses():
            try:
                async for request in requests:
                    entered.set()
                    await asyncio.sleep(60)
                    yield response_pb2.DiscoverResponse()
            finally:
                stopped.set()
        return responses()

    monkeypatch.setattr(FakeStub, "Discover", blocking_discover)
    pending = asyncio.create_task(ConsumerAPI(first).async_get_instances(
        GetInstancesRequest(namespace="ns", service="pending")))
    assert await asyncio.to_thread(entered.wait, 3)
    first.destroy()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(pending, 3)
    assert stopped.is_set()
    assert first.get_engine().svc_connector._streams == {}
    assert first.get_engine().svc_connector._stream_locks == {}
    assert all(channel.closed for channel in contexts.channels if channel.address == "first:8091")
    assert (await ConsumerAPI(second).async_get_instances(
        GetInstancesRequest(namespace="ns", service="svc"))).get_instances()[0].get_id() == "second:8091"
