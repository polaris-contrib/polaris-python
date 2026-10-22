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

"""Java discovery semantics with INSTANCE-only caching and offline fallback."""

import asyncio
from pathlib import Path

import pytest
from polarismesh_specification.api.v1.service_manage import response_pb2

from polaris import ConsumerAPI, ProviderAPI, init_context_by_config
from polaris.pkg.model.core import EventType, ServiceEventKey
from polaris.pkg.model.error import SDKError, ErrorCode
from polaris.pkg.model.server import InstanceDiscoverRequest, InstanceRegisterRequest, InstanceHeartbeatRequest
from polaris.pkg.model.service import (GetInstancesRequest, GetHealthyInstancesRequest,
                                      GetAllInstancesRequest, GetOneInstanceRequest, CBStatusEnum)
from tests.test_ai import runtime, instance
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection


@pytest.mark.asyncio
async def test_all_healthy_and_candidates_do_not_mutate_snapshot_or_allocate_permits(runtime):
    stub, context, _ = runtime
    stub.instances = [instance("ok", 8080), instance("open", 8081),
                      instance("half", 8082), instance("isolated", 8083, isolate={"value": True})]
    down = instance("down", 8084)
    down.healthy.value = False
    zero = instance("zero", 8085)
    zero.weight.value = 0
    stub.instances.extend([down, zero])
    api = ConsumerAPI(context)
    all_nodes = await api.async_get_all_instances(GetAllInstancesRequest(namespace="ns", service="svc"))
    nodes = {node.get_id(): node for node in all_nodes.instances}
    nodes["open"].get_circuit_breaker_status().status = CBStatusEnum.Open
    nodes["half"].get_circuit_breaker_status().status = CBStatusEnum.HalfOpen
    candidates = await api.async_get_instances(GetInstancesRequest(namespace="ns", service="svc"))
    assert [node.get_id() for node in candidates.instances] == ["ok", "half"]
    healthy = await api.async_get_healthy_instances(GetHealthyInstancesRequest(namespace="ns", service="svc"))
    assert [node.get_id() for node in healthy.instances] == ["ok", "open", "half"]
    assert nodes["half"].get_circuit_breaker_status().requests_after_half_open == 0
    assert len(all_nodes.instances) == 6
    assert list(context.engine.registry.service_map) == [ServiceEventKey("ns", "svc", EventType.Instance)]


@pytest.mark.asyncio
@pytest.mark.parametrize("periodic", [False, True])
async def test_service_not_found_removes_backup_memory_and_stream(runtime, periodic):
    stub, context, create = runtime
    stub.instances = [instance()]
    request = GetAllInstancesRequest(namespace="ns", service="svc")
    await ConsumerAPI(context).async_get_all_instances(request)
    await asyncio.to_thread(context.engine.file_cache.queue.join)
    files = list(Path(context.config.get_consumer().get_local_cache().persist_dir).glob("svc#ns#svc#*.json"))
    assert len(files) == 1
    if not periodic:
        context.destroy()
        context = create()

    def missing(requests, timeout=None, metadata=()):
        async def responses():
            async for req in requests:
                yield response_pb2.DiscoverResponse(code={"value": 400301}, type=1, service=req.service)
        return responses()

    stub.Discover = missing
    if periodic:
        await context.engine._run_async(context.engine.svc_connector.stop_discover(
            InstanceDiscoverRequest(1, "svc", "ns")))
        task = next(iter(context.engine.update_task_set.values()))
        task.last_update_time = 0
        await context.engine._run_async(context.engine.process_update_task(task))
    else:
        with pytest.raises(SDKError) as error:
            await ConsumerAPI(context).async_get_all_instances(request)
        assert error.value.server_code == 400301
    assert not files[0].exists()
    assert context.engine.registry.service_map == context.engine.update_task_set == {}
    assert context.engine.svc_connector._streams == {}


@pytest.mark.asyncio
async def test_no_change_preserves_snapshot_identity_and_backup(runtime):
    stub, context, _ = runtime
    stub.instances = [instance()]
    await ConsumerAPI(context).async_get_all_instances(GetAllInstancesRequest(namespace="ns", service="svc"))
    task = next(iter(context.engine.update_task_set.values()))
    previous = task.cache_obj.value

    async def unchanged(request, use_discover_cache=True):
        raise SDKError(ErrorCode.ErrCodeDataNotChange, "unchanged", server_code=200001)

    context.engine.svc_connector.discover = unchanged
    task.last_update_time = 0
    await context.engine._run_async(context.engine.process_update_task(task))
    assert task.cache_obj.value is previous
    assert task.last_update_time > 0


@pytest.mark.asyncio
async def test_same_revision_skips_backup_then_new_empty_snapshot_replaces_instances(runtime, monkeypatch):
    stub, context, _ = runtime
    stub.instances = [instance()]
    api = ConsumerAPI(context)
    request = GetAllInstancesRequest(namespace="ns", service="svc")
    await api.async_get_all_instances(request)
    await asyncio.to_thread(context.engine.file_cache.queue.join)
    task = next(iter(context.engine.update_task_set.values()))
    snapshot = task.cache_obj.value
    writes = []
    save = context.engine.file_cache.save

    def record(request, response):
        writes.append(response.service.revision.value)
        return save(request, response)

    revision = snapshot.revision

    async def updated(request, use_discover_cache=True):
        return response_pb2.DiscoverResponse(code={"value": 200000}, type=1,
            service={"name": {"value": "svc"}, "namespace": {"value": "ns"},
                     "revision": {"value": revision}}, instances=[])

    monkeypatch.setattr(context.engine.file_cache, "save", record)
    monkeypatch.setattr(context.engine.svc_connector, "discover", updated)
    task.last_update_time = 0
    await context.engine._run_async(context.engine.process_update_task(task))
    assert task.cache_obj.value is snapshot and not writes
    revision = "empty-new-revision"
    task.last_update_time = 0
    await context.engine._run_async(context.engine.process_update_task(task))
    response = await api.async_get_all_instances(request)
    assert response.instances == [] and response.revision == revision
    assert writes == [revision]


@pytest.mark.parametrize("query", [GetInstancesRequest(), GetAllInstancesRequest(namespace="ns"),
    GetHealthyInstancesRequest(namespace="ns", service="svc", timeout=-1)])
def test_invalid_instance_query(query):
    with pytest.raises(SDKError):
        query.validate()


@pytest.mark.asyncio
async def test_system_clusters_use_bootstrap_then_independent_addresses_and_refresh(runtime, monkeypatch):
    stub, original, _ = runtime
    config = original.config
    config.get_global().get_server_connector().addresses = ["bootstrap:8091"]
    system = config.get_global().get_system()
    for cluster, name in ((system.discover_cluster, "discover"), (system.health_check_cluster, "health"),
                          (system.monitor_cluster, "monitor")):
        cluster.namespace, cluster.service, cluster.refresh_interval = "system", name, 12345
    config.get_global().get_stat_reporter().enable = False
    destinations = []
    ports = {"discover": 9001, "health": 9002, "monitor": 9004}

    async def rpc_stub(connection, address):
        destinations.append((connection.target_service, address))
        return stub

    def discover(requests, **kwargs):
        async def responses():
            async for request in requests:
                name = request.service.name.value
                nodes = [instance(name, ports[name])] if name in ports else [instance("business", 8080)]
                yield response_pb2.DiscoverResponse(code={"value": 200000}, type=1,
                    service={"name": request.service.name, "namespace": request.service.namespace,
                             "revision": {"value": str(ports.get(name, 1))}}, instances=nodes)
        return responses()

    monkeypatch.setattr(GrpcConnection, "_stub", rpc_stub)
    stub.Discover = discover
    context = init_context_by_config(config)
    connector = context.engine.svc_connector
    try:
        await ProviderAPI(context).async_register(InstanceRegisterRequest(
            namespace="ns", service="svc", service_token="token", host="127.0.0.1", port=8080))
        await ProviderAPI(context).async_heartbeat(InstanceHeartbeatRequest(
            instance_id="registered", namespace="ns", service="svc", service_token="token", host="127.0.0.1", port=8080))
        await ConsumerAPI(context).async_get_all_instances(GetAllInstancesRequest(namespace="ns", service="svc"))
        assert (("system", "discover"), "127.0.0.1:9001") in destinations
        assert (("system", "health"), "127.0.0.1:9002") in destinations
        monitor_node = await context.engine._run_async(context.engine._async_get_one_instance(
            GetOneInstanceRequest(namespace="system", service="monitor")))
        assert monitor_node.get_port() == 9004
        assert any(address == "bootstrap:8091" for _, address in destinations)
        assert connector._cluster_connections[("system", "discover")] is not connector._cluster_connections[("system", "health")]
        key = ServiceEventKey("system", "discover", EventType.Instance)
        task = context.engine.update_task_set[key]
        assert task.update_interval == 12345
        monitor_key = ServiceEventKey("system", "monitor", EventType.Instance)
        assert context.engine.update_task_set[monitor_key].update_interval == 12345
        ports["discover"] = 9003
        task.last_update_time = 0
        await context.engine._run_async(context.engine.process_update_task(task))
        await context.engine._run_async(connector._connection())
        assert connector._cluster_connections[("system", "discover")]._addresses == ["127.0.0.1:9003"]
        for cache in context.engine.registry.service_map.values():
            cache.last_visit_time = 0
        expired = await context.engine._run_async(context.engine.registry.expire_services())
        assert key not in expired
    finally:
        connections = list(connector._cluster_connections.values())
        context.destroy()
    assert connector._streams == connector._stream_locks == connector._cluster_connections == {}
    assert all(connection._closed for connection in connections)


@pytest.mark.asyncio
async def test_server_addresses_switch_periodically(runtime, monkeypatch):
    stub, original, _ = runtime
    config = original.config
    connector_config = config.get_global().get_server_connector()
    connector_config.addresses = ["first:8091", "second:8091"]
    connector_config.connection_idle_timeout = 100
    connector_config.server_switch_interval = 101
    config.get_global().get_stat_reporter().enable = False
    addresses = []

    async def rpc_stub(connection, address):
        addresses.append(address)
        return stub

    monkeypatch.setattr(GrpcConnection, "_stub", rpc_stub)
    context = init_context_by_config(config)
    try:
        assert context.engine.svc_connector.connection._switch_task is not None
        await asyncio.sleep(0.13)
        await ProviderAPI(context).async_register(InstanceRegisterRequest(
            namespace="ns", service="svc", service_token="token", host="127.0.0.1", port=8080))
        assert addresses[-1] == "second:8091"
    finally:
        context.destroy()
    assert context.engine.svc_connector.connection._switch_task is None
