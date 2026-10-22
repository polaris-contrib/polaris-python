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

"""Provider lifecycle tests with fake RPCs on the real SDK runtime."""

from __future__ import annotations

import asyncio
import copy
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

from polaris.api.config import SDKContext
from polaris.api.consumer import ConsumerAPI
from polaris.api.provider import ProviderAPI
from polaris.pkg.config.api import Configuration
from polaris.pkg.flow.impl import Engine
from polaris.pkg.flow.register import RegisterStateManager
from polaris.pkg.flow.sync_flow import SyncEngine
from polaris.pkg.model.error import ErrorCode, SDKError, ServerCode
from polaris.pkg.model.server import (
    InstanceDeRegisterRequest,
    InstanceHeartbeatRequest,
    InstanceRegisterRequest,
    InstanceRegisterResponse,
)
from polaris.pkg.model.service import GetInstancesRequest
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection
from polaris.plugin.server_connector.grpc_connector.grpc_client import GrpcConnector
from polaris.plugin_manager import InitContext, PluginManager


def registration(**kwargs):
    return InstanceRegisterRequest("svc", "service-token", "ns", "127.0.0.1", 8080, **kwargs)


def deregistration(instance_id="instance-id"):
    return InstanceDeRegisterRequest("svc", "service-token", "ns", "127.0.0.1", 8080, instance_id)


def heartbeat_request():
    return InstanceHeartbeatRequest("svc", "service-token", "ns", "instance-id", "127.0.0.1", 8080)


class FakeProviderStub:
    """Record protobuf calls, loop ownership and cancellation without network I/O."""

    def __init__(self):
        self.calls = []
        self.register_code = ServerCode.ExecuteSuccess
        self.instance_id = "instance-id"
        self.deregister_code = ServerCode.ExecuteSuccess
        self.heartbeat_code = ServerCode.ExecuteSuccess
        self.register_started = threading.Event()
        self.heartbeat_started = threading.Event()
        self.heartbeat_cancelled = threading.Event()
        self.block_heartbeat = False
        self.block_register = False
        self.register_release = None

    def record(self, method, request, metadata):
        self.calls.append((method, copy.deepcopy(request), dict(metadata),
                           asyncio.get_running_loop(), threading.current_thread()))

    async def RegisterInstance(self, request, timeout=None, metadata=()):
        self.record("register", request, metadata)
        self.register_started.set()
        if self.block_register:
            await self.register_release.wait()
        return response_pb2.Response(code={"value": self.register_code},
                                     instance=service_pb2.Instance(id={"value": self.instance_id}))

    async def DeregisterInstance(self, request, timeout=None, metadata=()):
        self.record("deregister", request, metadata)
        return response_pb2.Response(code={"value": self.deregister_code})

    async def Heartbeat(self, request, timeout=None, metadata=()):
        self.record("heartbeat", request, metadata)
        self.heartbeat_started.set()
        if self.block_heartbeat:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.heartbeat_cancelled.set()
                raise
        return response_pb2.Response(code={"value": self.heartbeat_code})


@pytest.fixture
def provider_runtime(monkeypatch):
    config = Configuration()
    config.set_default()
    connector = GrpcConnector(InitContext(config=config))
    stub = FakeProviderStub()

    async def fake_stub(self, address):
        return stub

    monkeypatch.setattr(GrpcConnection, "_stub", fake_stub)
    engine = Engine(config=config, connector=connector)
    ready = threading.Event()

    def run_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        engine.loop = loop
        ready.set()
        try:
            loop.run_forever()
        finally:
            pending = list(asyncio.all_tasks(loop))
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            engine.loop = None

    engine.thread = threading.Thread(target=run_loop, daemon=True)
    engine.thread.start()
    assert ready.wait(2)
    provider = ProviderAPI(SDKContext(config, PluginManager(), engine))
    try:
        yield provider, engine, stub
    finally:
        provider.destroy()
        engine.thread.join(2)
        assert not engine.thread.is_alive()


def test_sync_provider_operations_use_one_runtime_loop(provider_runtime):
    provider, engine, stub = provider_runtime
    request = registration()
    assert provider.register(request).instance_id == "instance-id"
    assert request.instance_id == "instance-id"
    assert provider.heartbeat(heartbeat_request()) is None
    assert provider.deregister(deregistration()) is None
    assert [call[0] for call in stub.calls] == ["register", "heartbeat", "deregister"]
    assert all(call[3] is engine.loop and call[4] is engine.thread for call in stub.calls)
    assert "async-regis" not in stub.calls[0][2]
    assert not stub.calls[0][1].HasField("health_check")


@pytest.mark.asyncio
async def test_async_provider_operations_use_same_runtime_loop(provider_runtime):
    provider, engine, stub = provider_runtime
    assert (await provider.async_register(registration())).instance_id == "instance-id"
    assert await provider.async_heartbeat(heartbeat_request()) is None
    assert await provider.async_deregister(deregistration()) is None
    assert all(call[3] is engine.loop and call[4] is engine.thread for call in stub.calls)


@pytest.mark.parametrize("method", ["register_instance", "register"])
def test_sync_automatic_registration_uses_default_ttl_and_headers(provider_runtime, method):
    provider, engine, stub = provider_runtime
    request = registration(auto_heartbeat=method == "register")
    assert getattr(provider, method)(request).instance_id == "instance-id"
    assert request.ttl == 5
    assert request.auto_heartbeat is True
    assert stub.calls[0][2]["async-regis"] == "true"
    assert stub.calls[0][1].health_check.heartbeat.ttl.value == 5
    assert stub.calls[0][1].health_check.type == service_pb2.HealthCheck.HEARTBEAT
    assert len(engine.register_states._states) == 1


@pytest.mark.asyncio
async def test_async_automatic_heartbeat_runs_after_ttl_and_stops_on_deregister(provider_runtime):
    provider, engine, stub = provider_runtime
    request = registration(ttl=1, metadata={"original": "value"})
    await provider.async_register_instance(request)
    assert not stub.heartbeat_started.is_set()
    request.host = "mutated-host"
    request.service_token = "mutated-token"
    assert await asyncio.to_thread(stub.heartbeat_started.wait, 2)
    heartbeat = next(call[1] for call in stub.calls if call[0] == "heartbeat")
    assert heartbeat.host.value == "127.0.0.1"
    assert heartbeat.service_token.value == "service-token"
    assert heartbeat.id.value == "instance-id"
    # ID-only deregistration must stop the task even without the original address.
    await provider.async_deregister(InstanceDeRegisterRequest("", "service-token", "", "", 0, "instance-id"))
    assert engine.register_states._states == {}
    call_count = len(stub.calls)
    await asyncio.sleep(1.05)
    assert len(stub.calls) == call_count


@pytest.mark.parametrize("ttl", [0, -1, 1.5, True, "5", 2 ** 32])
def test_registration_rejects_invalid_ttl(provider_runtime, ttl):
    provider, engine, stub = provider_runtime
    with pytest.raises(SDKError) as raised:
        provider.register_instance(registration(ttl=ttl))
    assert raised.value.err_code == ErrorCode.ErrCodeAPIInvalidArgument
    assert stub.calls == []


@pytest.mark.parametrize("method,request_factory", [
    ("register", registration), ("register_instance", registration),
    ("heartbeat", heartbeat_request), ("deregister", deregistration),
])
@pytest.mark.asyncio
async def test_sync_provider_rejects_active_user_loop(provider_runtime, method, request_factory):
    provider, engine, stub = provider_runtime
    with pytest.raises(SDKError, match="async_") as raised:
        getattr(provider, method)(request_factory())
    assert raised.value.err_code == ErrorCode.ErrCodeInvalidStateError
    assert stub.calls == []


@pytest.mark.asyncio
async def test_sync_consumer_rejects_active_user_loop(provider_runtime):
    provider, engine, stub = provider_runtime
    with pytest.raises(SDKError, match="async_"):
        ConsumerAPI(provider.context).get_instances(GetInstancesRequest(service="svc", namespace="ns"))


@pytest.mark.asyncio
async def test_sync_provider_rejects_owner_loop(provider_runtime):
    provider, engine, stub = provider_runtime

    async def call_sync():
        provider.register(registration())

    with pytest.raises(SDKError, match="async_"):
        await engine._run_async(call_sync())
    assert stub.calls == []


@pytest.mark.parametrize("method,request_factory", [
    ("register", registration), ("register_instance", registration),
    ("heartbeat", heartbeat_request), ("deregister", deregistration),
])
def test_sync_provider_rejects_destroyed_context(provider_runtime, method, request_factory):
    provider, engine, stub = provider_runtime
    provider.destroy()
    with pytest.raises(SDKError) as raised:
        getattr(provider, method)(request_factory())
    assert raised.value.err_code == ErrorCode.ErrCodeInvalidStateError
    assert stub.calls == []


@pytest.mark.parametrize("method,request_factory", [
    ("async_register", registration), ("async_register_instance", registration),
    ("async_heartbeat", heartbeat_request), ("async_deregister", deregistration),
])
@pytest.mark.asyncio
async def test_async_provider_rejects_destroyed_context(provider_runtime, method, request_factory):
    provider, engine, stub = provider_runtime
    provider.destroy()
    with pytest.raises(SDKError) as raised:
        await getattr(provider, method)(request_factory())
    assert raised.value.err_code == ErrorCode.ErrCodeInvalidStateError


@pytest.mark.asyncio
async def test_failed_initial_registration_never_starts_heartbeats(provider_runtime):
    provider, engine, stub = provider_runtime
    stub.register_code = 500000
    with pytest.raises(SDKError) as raised:
        await provider.async_register_instance(registration())
    assert raised.value.server_code == 500000
    assert engine.register_states._states == {}


def test_failed_deregistration_still_stops_automatic_heartbeats(provider_runtime):
    provider, engine, stub = provider_runtime
    provider.register_instance(registration())
    state = next(iter(engine.register_states._states.values()))
    stub.deregister_code = 500000
    with pytest.raises(SDKError) as raised:
        provider.deregister(deregistration())
    assert raised.value.server_code == 500000
    assert state.heartbeat_task.cancelled()
    assert engine.register_states._states == {}


@pytest.mark.asyncio
async def test_deregistration_cancels_inflight_heartbeat(provider_runtime):
    provider, engine, stub = provider_runtime
    stub.block_heartbeat = True
    await provider.async_register_instance(registration(ttl=1))
    assert await asyncio.to_thread(stub.heartbeat_started.wait, 2)
    await provider.async_deregister(deregistration())
    assert stub.heartbeat_cancelled.is_set()
    assert engine.register_states._states == {}


@pytest.mark.asyncio
async def test_destroy_cancels_inflight_heartbeat_before_closing_connector(provider_runtime):
    provider, engine, stub = provider_runtime
    stub.block_heartbeat = True
    await provider.async_register_instance(registration(ttl=1))
    assert await asyncio.to_thread(stub.heartbeat_started.wait, 2)
    provider.destroy()
    assert stub.heartbeat_cancelled.is_set()
    assert engine.register_states._states == {}
    assert engine.svc_connector.connection._closed
    assert not engine.thread.is_alive()


def test_repeated_registration_replaces_task_without_duplicates(provider_runtime):
    provider, engine, stub = provider_runtime
    provider.register_instance(registration())
    old = next(iter(engine.register_states._states.values()))
    provider.register_instance(registration(ttl=10))
    new = next(iter(engine.register_states._states.values()))
    assert len(engine.register_states._states) == 1
    assert old.heartbeat_task.cancelled()
    assert new.request.ttl == 10


def test_concurrent_registration_and_deregistration_are_serialized(provider_runtime):
    provider, engine, stub = provider_runtime

    async def setup():
        stub.register_release = asyncio.Event()

    engine._run_sync(setup())
    stub.block_register = True
    with ThreadPoolExecutor(2) as pool:
        register = pool.submit(provider.register_instance, registration())
        assert stub.register_started.wait(2)
        deregister = pool.submit(provider.deregister, deregistration(instance_id=""))
        engine.loop.call_soon_threadsafe(stub.register_release.set)
        assert register.result(2).instance_id == "instance-id"
        assert deregister.result(2) is None
    assert [call[0] for call in stub.calls] == ["register", "deregister"]
    assert engine.register_states._states == {}


def test_legacy_sync_engine_inherits_shared_provider_flows():
    assert SyncEngine.sync_register is Engine.sync_register
    assert SyncEngine.sync_deregister is Engine.sync_deregister
    assert SyncEngine.sync_heartbeat is Engine.sync_heartbeat


class FakeLifecycleRPC:
    def __init__(self):
        self.error = None
        self.register_error = None
        self.heartbeats = []
        self.registrations = []
        self.register_started = asyncio.Event()
        self.register_release = None

    async def heartbeat(self, request):
        self.heartbeats.append(copy.deepcopy(request))
        if self.error:
            raise self.error

    async def register(self, request):
        self.registrations.append(copy.deepcopy(request))
        self.register_started.set()
        if self.register_release is not None:
            await self.register_release.wait()
        if self.register_error:
            raise self.register_error
        return InstanceRegisterResponse("replacement-id")


@pytest.fixture
async def lifecycle():
    rpc = FakeLifecycleRPC()
    manager = RegisterStateManager(rpc.register, rpc.heartbeat, 30000)
    request = registration(ttl=5, auto_heartbeat=True, instance_id="original-id")
    await manager.put(request)
    state = next(iter(manager._states.values()))
    state.first_register_time -= 31
    try:
        yield manager, state, rpc
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_two_not_found_heartbeats_trigger_reregistration(lifecycle):
    manager, state, rpc = lifecycle
    rpc.error = SDKError(ErrorCode.ErrCodeServerError, "missing", ServerCode.NotFoundResource)
    await manager._heartbeat_once(state)
    assert state.re_register_task is None
    await manager._heartbeat_once(state)
    await state.re_register_task
    assert len(rpc.registrations) == 1
    assert state.request.instance_id == "replacement-id"
    assert state.heartbeat_fail_count == state.re_register_count == 0
    rpc.error = None
    await manager._heartbeat_once(state)
    assert rpc.heartbeats[-1].instance_id == "replacement-id"


@pytest.mark.asyncio
async def test_original_id_deregister_removes_recovered_instance(provider_runtime):
    provider, engine, stub = provider_runtime
    await provider.async_register_instance(registration())

    async def recover():
        state = next(iter(engine.register_states._states.values()))
        state.first_register_time -= 31
        stub.heartbeat_code = ServerCode.NotFoundResource
        stub.instance_id = "replacement-id"
        await engine.register_states._heartbeat_once(state)
        await engine.register_states._heartbeat_once(state)
        await state.re_register_task
        assert state.request.instance_id == "replacement-id"

    await engine._run_async(recover())
    await provider.async_deregister(InstanceDeRegisterRequest("", "service-token", "", "", 0, "instance-id"))
    assert engine.register_states._states == {}
    assert stub.calls[-1][0] == "deregister"
    assert stub.calls[-1][1].id.value == "replacement-id"


@pytest.mark.asyncio
async def test_removing_one_instance_keeps_other_heartbeats(lifecycle):
    manager, state, rpc = lifecycle
    other = InstanceRegisterRequest("svc", "service-token", "ns", "127.0.0.1", 8081,
                                    ttl=5, auto_heartbeat=True, instance_id="other-id")
    await manager.put(other)
    await manager.remove(deregistration(instance_id="original-id"))
    assert state.heartbeat_task.cancelled()
    remaining = next(iter(manager._states.values()))
    assert remaining.request.port == 8081
    assert not remaining.heartbeat_task.done()


@pytest.mark.asyncio
async def test_unknown_id_does_not_stop_instance_at_same_address(lifecycle):
    manager, state, rpc = lifecycle
    await manager.remove(deregistration(instance_id="unknown-id"))
    assert len(manager._states) == 1
    assert not state.heartbeat_task.done()


@pytest.mark.asyncio
async def test_shutdown_on_sdk_loop_stops_tasks_without_deadlock(provider_runtime):
    provider, engine, stub = provider_runtime
    await provider.async_register_instance(registration())
    destroyed = threading.Event()

    async def close():
        provider.destroy()
        destroyed.set()

    asyncio.run_coroutine_threadsafe(close(), engine.loop)
    assert await asyncio.to_thread(destroyed.wait, 2)
    await asyncio.to_thread(engine.thread.join, 2)
    assert not engine.thread.is_alive()
    assert engine.loop is None
    assert engine.register_states._states == {}


@pytest.mark.parametrize("error", [
    SDKError(ErrorCode.ErrCodeNetworkError, "network"),
    SDKError(ErrorCode.ErrCodeServerError, "server", 500000),
    RuntimeError("unexpected failure"),
])
@pytest.mark.asyncio
async def test_other_errors_keep_heartbeats_running_without_reregistering(lifecycle, error):
    manager, state, rpc = lifecycle
    state.heartbeat_fail_count = 1
    rpc.error = error
    for _ in range(4):
        await manager._heartbeat_once(state)
    assert len(rpc.heartbeats) == 4
    assert state.heartbeat_fail_count == 0
    assert state.re_register_task is None


@pytest.mark.asyncio
async def test_success_resets_consecutive_not_found_counter(lifecycle):
    manager, state, rpc = lifecycle
    rpc.error = SDKError(ErrorCode.ErrCodeServerError, "missing", ServerCode.NotFoundResource)
    await manager._heartbeat_once(state)
    rpc.error = None
    await manager._heartbeat_once(state)
    rpc.error = SDKError(ErrorCode.ErrCodeServerError, "missing", ServerCode.NotFoundResource)
    await manager._heartbeat_once(state)
    assert state.heartbeat_fail_count == 1
    assert state.re_register_task is None


@pytest.mark.asyncio
async def test_reregister_respects_minimum_interval(lifecycle):
    manager, state, rpc = lifecycle
    state.first_register_time = asyncio.get_running_loop().time()
    rpc.error = SDKError(ErrorCode.ErrCodeServerError, "missing", ServerCode.NotFoundResource)
    for _ in range(3):
        await manager._heartbeat_once(state)
    assert state.re_register_task is None
    state.first_register_time -= 31
    await manager._heartbeat_once(state)
    await state.re_register_task
    assert len(rpc.registrations) == 1


@pytest.mark.asyncio
async def test_failed_reregister_keeps_heartbeats_and_uses_capped_backoff(lifecycle, monkeypatch):
    manager, state, rpc = lifecycle
    rpc.error = SDKError(ErrorCode.ErrCodeServerError, "missing", ServerCode.NotFoundResource)
    rpc.register_error = SDKError(ErrorCode.ErrCodeNetworkError, "register failed")
    await manager._heartbeat_once(state)
    await manager._heartbeat_once(state)
    await state.re_register_task
    assert state.re_register_count == 1
    delays = []
    reregister = manager._re_register

    async def immediate_reregister(state, delay):
        delays.append(delay)
        await reregister(state, 0)

    monkeypatch.setattr(manager, "_re_register", immediate_reregister)
    monkeypatch.setattr("polaris.pkg.flow.register.random.randrange", lambda value: 0)
    for _ in range(6):
        await manager._heartbeat_once(state)
        await state.re_register_task
    assert delays == [5, 10, 20, 40, 60, 60]
    assert len(rpc.heartbeats) == 8
    assert not state.heartbeat_task.done()


@pytest.mark.asyncio
async def test_reregister_is_not_duplicated_while_rpc_is_pending(lifecycle):
    manager, state, rpc = lifecycle
    rpc.error = SDKError(ErrorCode.ErrCodeServerError, "missing", ServerCode.NotFoundResource)
    rpc.register_release = asyncio.Event()
    await manager._heartbeat_once(state)
    await manager._heartbeat_once(state)
    await asyncio.wait_for(rpc.register_started.wait(), 1)
    for _ in range(3):
        await manager._heartbeat_once(state)
    assert len(rpc.registrations) == 1
    assert state.re_register_count == 1
    rpc.register_release.set()
    await state.re_register_task


@pytest.mark.asyncio
async def test_deregister_cancels_delayed_reregister(lifecycle):
    manager, state, rpc = lifecycle
    state.re_register_count = 2
    rpc.error = SDKError(ErrorCode.ErrCodeServerError, "missing", ServerCode.NotFoundResource)
    await manager._heartbeat_once(state)
    await manager._heartbeat_once(state)
    task = state.re_register_task
    await manager.remove(deregistration(instance_id="original-id"))
    assert task.cancelled()
    assert state.heartbeat_task.cancelled()
    assert rpc.registrations == []


@pytest.mark.asyncio
async def test_destroy_cancels_inflight_reregister(lifecycle):
    manager, state, rpc = lifecycle
    rpc.error = SDKError(ErrorCode.ErrCodeServerError, "missing", ServerCode.NotFoundResource)
    rpc.register_release = asyncio.Event()
    await manager._heartbeat_once(state)
    await manager._heartbeat_once(state)
    await asyncio.wait_for(rpc.register_started.wait(), 1)
    task = state.re_register_task
    await manager.close()
    assert task.cancelled()
    assert manager._states == {}


@pytest.mark.asyncio
async def test_replacement_id_still_cancels_old_schedule(lifecycle):
    manager, state, rpc = lifecycle
    replacement = registration(ttl=10, auto_heartbeat=True, instance_id="replacement-id")
    await manager.put(replacement)
    assert state.heartbeat_task.cancelled()
    assert len(manager._states) == 1
    assert next(iter(manager._states.values())).request.instance_id == "replacement-id"
