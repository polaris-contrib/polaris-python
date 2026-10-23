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

"""Event center dispatch and real capability event emission."""

import pytest

from polaris.pkg.model.context import ContextKeyEventCenter, new_value_context
from polaris.pkg.model.core import ServiceEventKey, EventType
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.pkg.model.event import (
    EventCenter, SDKEvent, SDKEventName, SDKEventType, now_event,
)
from polaris.pkg.model.service import GetInstancesRequest
from tests.test_context import contexts, discover
from tests.test_localregistry import make_cache
from polaris import Configuration, ConsumerAPI, ProviderAPI
from polaris.pkg.model.server import InstanceDeRegisterRequest, InstanceRegisterRequest
from polaris.pkg.model.core import ServiceKey
from polaris.pkg.model.service import RetStatus, ServiceCallResult
from tests.test_ai import runtime


def event(name=SDKEventName.ON_SERVICE_ADDED, event_type=SDKEventType.INSTANCE):
    return now_event("client", event_type, name, namespace="ns", service="svc")


def test_event_center_filters_types_and_isolates_listener_errors():
    center = EventCenter(new_value_context())
    received = []

    def broken(value):
        raise RuntimeError("listener failed")

    class Listener:
        def on_sdk_event(self, value):
            received.append(value)

    listener = Listener()
    center.register_listener(broken)
    center.register_listener(listener, SDKEventType.INSTANCE)
    instance_event = event()
    circuit_event = event(SDKEventName.CIRCUIT_BREAKER_OPEN, SDKEventType.CIRCUIT_BREAKING)
    center.publish(instance_event)
    center.publish(circuit_event)
    assert received == [instance_event]

    center.unregister_listener(listener, SDKEventType.INSTANCE)
    center.publish(event())
    assert received == [instance_event]
    center.close()
    assert center._listeners == []


@pytest.mark.asyncio
async def test_resource_add_update_and_delete_events():
    cache, engine = make_cache()
    value_context = new_value_context()
    center = EventCenter(value_context)
    cache.init_ctx.value_ctx.set_value(ContextKeyEventCenter, center)
    received = []
    center.register_listener(lambda item: received.append(item), SDKEventType.INSTANCE)
    key = ServiceEventKey("Test", "svc", EventType.Instance)

    await cache.load_instances("svc", "Test")
    snapshot = cache.service_map[key].value
    cache.update_service(key, snapshot)
    await cache.remove_service(key, cache.service_map[key])
    assert [item.event_name for item in received] == [
        SDKEventName.ON_SERVICE_ADDED, SDKEventName.ON_SERVICE_UPDATED, SDKEventName.ON_SERVICE_DELETED,
    ]
    assert received[0].old_value is None
    assert received[0].new_value is snapshot


@pytest.mark.asyncio
async def test_disk_backup_first_load_emits_added(monkeypatch):
    from tests.test_localregistry import FakeConnector
    from polaris.plugin.local_registry import local_cache as registry_module

    cache, _ = make_cache()
    center = EventCenter(new_value_context())
    cache.init_ctx.value_ctx.set_value(ContextKeyEventCenter, center)
    received = []
    center.register_listener(lambda item: received.append(item), SDKEventType.INSTANCE)
    key = ServiceEventKey("Test", "svc", EventType.Instance)
    disk = await FakeConnector().discover(type("Request", (), {
        "namespace": "Test", "name": "svc", "type": 1,
    })())

    async def load_disk(engine, request):
        return disk

    async def unchanged(request, use_discover_cache=True):
        raise SDKError(ErrorCode.ErrCodeDataNotChange, "unchanged")

    monkeypatch.setattr(registry_module, "load_file_cache", load_disk)
    monkeypatch.setattr(cache.init_ctx.value_ctx.get_value("engine").svc_connector,
                        "discover", unchanged)

    await cache.load_instances("svc", "Test")
    assert [item.event_name for item in received] == [SDKEventName.ON_SERVICE_ADDED]
    assert received[0].old_value is None
    assert received[0].new_value is cache.service_map[key].value


@pytest.mark.asyncio
async def test_idle_eviction_emits_deleted(monkeypatch):
    from polaris.plugin.local_registry import local_cache as registry_module

    cache, _ = make_cache()
    center = EventCenter(new_value_context())
    cache.init_ctx.value_ctx.set_value(ContextKeyEventCenter, center)
    received = []
    center.register_listener(lambda item: received.append(item), SDKEventType.INSTANCE)
    cache.config.get_consumer().get_local_cache().service_expire_time = 5000
    clock = [100.0]
    monkeypatch.setattr(registry_module.time, "monotonic", lambda: clock[0])

    await cache.load_instances("svc", "Test")
    clock[0] = 110.0
    assert await cache.expire_services() == [ServiceEventKey("Test", "svc", EventType.Instance)]
    assert received[-1].event_name == SDKEventName.ON_SERVICE_DELETED
    assert received[-1].new_value is None


def test_context_resource_events_are_isolated(contexts):
    first, second = contexts("first"), contexts("second")
    first_events, second_events = [], []
    first.get_event_center().register_listener(first_events.append, SDKEventType.INSTANCE)
    second.get_event_center().register_listener(second_events.append, SDKEventType.INSTANCE)

    discover(first)
    assert [item.event_name for item in first_events] == [SDKEventName.ON_SERVICE_ADDED]
    assert second_events == []

    discover(second)
    assert [item.event_name for item in second_events] == [SDKEventName.ON_SERVICE_ADDED]
    assert len(first_events) == 1


def test_instance_circuit_breaker_state_change_emits_event(contexts, tmp_path):
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = ["event:8091"]
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "cache")
    circuit = config.get_consumer().get_circuit_breaker()
    circuit.default_error_count = 1
    circuit.sleep_window = 2000
    circuit.success_count_after_half_open = 1
    client = contexts("event", config)
    consumer = ConsumerAPI(client)
    events = []
    client.get_event_center().register_listener(events.append, SDKEventType.CIRCUIT_BREAKING)
    nodes = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test"))
    node = nodes.instances[0]
    consumer.sync_update_service_call_result(ServiceCallResult(
        node, RetStatus.RetFail, 500, 10))
    client.engine.do_circuit_break_for_service(ServiceKey("Test", "svc"), nodes)

    assert len(events) == 1
    assert events[0].event_type == SDKEventType.CIRCUIT_BREAKING
    assert events[0].event_name == SDKEventName.CIRCUIT_BREAKER_OPEN
    assert events[0].previous_status == "CLOSE"
    assert events[0].current_status == "OPEN"
    assert events[0].instance_id == node.get_id()
    assert events[0].additional == {"isolation_object": f"{node.get_host()}:{node.get_port()}"}


@pytest.mark.asyncio
async def test_successful_deregister_emits_instance_thread_end(runtime):
    _, context, _ = runtime
    events = []
    context.get_event_center().register_listener(events.append, SDKEventType.INSTANCE)
    provider = ProviderAPI(context)
    registration = InstanceRegisterRequest(
        namespace="ns", service="svc", service_token="token", host="127.0.0.1", port=8080)
    registered = await provider.async_register(registration)
    await provider.async_deregister(InstanceDeRegisterRequest(
        namespace="ns", service="svc", service_token="token", host="127.0.0.1", port=8080,
        instance_id=registered.instance_id))
    assert [item.event_name for item in events] == [SDKEventName.INSTANCE_THREAD_END]
    assert events[0].namespace == "ns"
    assert events[0].service == "svc"
    assert events[0].instance_id == "registered"
