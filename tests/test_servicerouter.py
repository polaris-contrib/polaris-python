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

import pytest
from polarismesh_specification.api.v1.service_manage import client_pb2, request_pb2, response_pb2
from polarismesh_specification.api.v1.service_manage import service_pb2

from polaris import ConsumerAPI, LogOptions, init_context_by_config
from polaris.pkg.config.api import Configuration
from polaris.pkg.model import service
from polaris.pkg.model.core import ServiceKey
from polaris.pkg.model.error import SDKError
from polaris.pkg.model.service import CBStatusEnum, CircuitBreakerStatus, GetOneInstanceRequest
from polaris import plugin_manager
from polaris.plugin.service_router.base import RouteInfo
from polaris.plugin.service_router.isolated import IsolatedRouter
from polaris.plugin.service_router.metadata import MetadataRouter
from polaris.plugin.service_router.recover import RecoverRouter
from polaris.plugin_manager import InitContext, PluginType
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection


def make_instance(instance_id, *, healthy=True, isolate=False, weight=100, metadata=None):
    value = service_pb2.Instance(
        id={"value": instance_id},
        host={"value": "127.0.0.1"},
        port={"value": 8080},
        healthy={"value": healthy},
        isolate={"value": isolate},
        weight={"value": weight},
    )
    if metadata:
        value.metadata.update(metadata)
    instance = service.Instance(value, ServiceKey("Test", "svc"))
    instance.local_value = service.DefaultInstanceLocalValue()
    return instance


def make_service(instances, service_metadata=None):
    service_value = service_pb2.Service(namespace={"value": "Test"}, name={"value": "svc"})
    if service_metadata:
        service_value.metadata.update(service_metadata)
    return service.ServiceInstances(service_value, instances)


def make_context():
    config = Configuration()
    config.set_default()
    return InitContext(config=config, plugins=plugin_manager.DefaultPluginManager)


def test_default_context_builds_java_router_chain():
    config = Configuration()
    config.set_default()
    assert config.get_consumer().get_service_router().get_chain() == []
    manager = plugin_manager.DefaultPluginManager.new_context_manager()
    init_ctx = InitContext(config=config, plugins=manager)
    before_cls = manager.get(PluginType.SERVICE_ROUTER, "isolatedRouter")
    core_cls = manager.get(PluginType.SERVICE_ROUTER, "metadataRouter")
    after_cls = manager.get(PluginType.SERVICE_ROUTER, "recoverRouter")
    before, core, after = before_cls(init_ctx), core_cls(init_ctx), after_cls(init_ctx)
    assert isinstance(before, IsolatedRouter)
    assert isinstance(core, MetadataRouter)
    assert isinstance(after, RecoverRouter)


def test_isolated_router_drops_isolated_and_zero_weight_instances():
    normal = make_instance("normal")
    isolated = make_instance("isolated", isolate=True)
    zero_weight = make_instance("zero-weight", weight=0)
    result = IsolatedRouter(make_context()).get_filtered_instances(
        RouteInfo(), make_service([normal, isolated, zero_weight]))
    assert result.instances == [normal]


def test_metadata_router_matches_all_requested_metadata():
    first = make_instance("first", metadata={"env": "prod", "lane": "one"})
    second = make_instance("second", metadata={"env": "prod"})
    route_info = RouteInfo(dest_service=service.ServiceInfo(service="svc", namespace="Test"),
                           metadata={"env": "prod", "lane": "one"})
    result = MetadataRouter(make_context()).get_filtered_instances(
        route_info, make_service([first, second]))
    assert result.instances == [first]


def test_metadata_router_failover_supports_all_others_and_none():
    router = MetadataRouter(make_context())
    wrong_value = make_instance("wrong-value", metadata={"env": "stable"})
    other = make_instance("other", metadata={"env": "stable"})
    missing = make_instance("missing")
    instances = make_service([wrong_value, other, missing])
    route_info = RouteInfo(dest_service=service.ServiceInfo(service="svc", namespace="Test"),
                           metadata={"env": "prod"})

    assert router.get_filtered_instances(route_info, instances).instances == [wrong_value, other, missing]
    route_info.metadata_failover_type = "others"
    assert router.get_filtered_instances(route_info, instances).instances == [missing]
    route_info.metadata_failover_type = "none"
    with pytest.raises(SDKError):
        router.get_filtered_instances(route_info, instances)


def test_metadata_router_rejects_invalid_plugin_failover():
    config = Configuration()
    config.set_default()
    config.get_consumer().get_service_router().plugin["metadataRouter"] = {
        "metadataFailOverType": "invalid"
    }
    with pytest.raises(SDKError):
        MetadataRouter(InitContext(config=config, plugins=plugin_manager.DefaultPluginManager))


def test_router_plugin_options_load_from_yaml_mapping():
    config = Configuration.from_dict({"consumer": {"serviceRouter": {
        "beforeChain": ["isolatedRouter"],
        "chain": ["metadataRouter"],
        "afterChain": ["recoverRouter"],
        "plugin": {
            "metadataRouter": {"metadataFailOverType": "others"},
            "recoverRouter": {
                "excludeCircuitBreakInstances": False,
                "allRecoverEnable": False,
            },
        },
    }}}, apply_env=False)
    config.set_default()
    init_ctx = InitContext(config=config, plugins=plugin_manager.DefaultPluginManager)
    assert MetadataRouter(init_ctx).failover == "others"
    recover = RecoverRouter(init_ctx)
    assert recover.exclude_circuit_break is False
    assert recover.all_recover is False


@pytest.mark.asyncio
async def test_get_one_instance_runs_configured_java_router_chain(monkeypatch, tmp_path):
    class Stub:
        async def ReportClient(self, request, timeout=None, metadata=()):
            return response_pb2.Response(
                code={"value": 200000},
                client=client_pb2.Client(),
            )

        def Discover(self, requests, timeout=None, metadata=()):
            async def responses():
                async for request in requests:
                    response = response_pb2.DiscoverResponse(
                        code={"value": 200000},
                        type=request.type,
                        service=service_pb2.Service(
                            name={"value": request.service.name.value},
                            namespace={"value": request.service.namespace.value},
                            revision={"value": "revision-1"},
                        ),
                    )
                    if request.type == request_pb2.DiscoverRequest.INSTANCE:
                        response.instances.append(service_pb2.Instance(
                            id={"value": "match"}, host={"value": "127.0.0.1"}, port={"value": 8081},
                            healthy={"value": True}, weight={"value": 100}, metadata={"env": "prod"}))
                        response.instances.append(service_pb2.Instance(
                            id={"value": "mismatch"}, host={"value": "127.0.0.1"}, port={"value": 8082},
                            healthy={"value": True}, weight={"value": 100}, metadata={"env": "stable"}))
                        response.instances.append(service_pb2.Instance(
                            id={"value": "unhealthy-match"}, host={"value": "127.0.0.1"}, port={"value": 8083},
                            healthy={"value": False}, weight={"value": 100}, metadata={"env": "prod"}))
                    yield response

            return responses()

    async def fake_stub(self, address):
        return Stub()

    monkeypatch.setattr(GrpcConnection, "_stub", fake_stub)
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = ["fake:8091"]
    config.get_consumer().get_service_router().chain = ["metadataRouter"]
    config.get_consumer().get_local_cache().persist_dir = str(tmp_path / "cache")
    context = init_context_by_config(config, log_options=LogOptions(file_path=tmp_path / "client.log"))
    engine = context.get_engine()
    consumer = ConsumerAPI(context)
    try:
        assert [type(router) for router in engine.before_router_chain] == [IsolatedRouter]
        assert [type(router) for router in engine.router_chain] == [MetadataRouter]
        assert [type(router) for router in engine.after_router_chain] == [RecoverRouter]
        instance = await consumer.async_get_one_instance(
            GetOneInstanceRequest(service="svc", namespace="Test", metadata={"env": "prod"}))
        assert instance.get_id() == "match"
    finally:
        context.destroy()


def test_recover_router_filters_unhealthy_and_open_instances_then_recovers_all():
    router = RecoverRouter(make_context())
    healthy = make_instance("healthy")
    unhealthy = make_instance("unhealthy", healthy=False)
    open_instance = make_instance("open")
    open_instance.local_value.cb_status = CircuitBreakerStatus(CBStatusEnum.Open)
    result = router.get_filtered_instances(
        RouteInfo(), make_service([healthy, unhealthy, open_instance]))
    assert result.instances == [healthy]

    result = router.get_filtered_instances(RouteInfo(), make_service([unhealthy, open_instance]))
    assert result.instances == [unhealthy, open_instance]

    route_info = RouteInfo(include_circuitbreak_instances=True)
    result = router.get_filtered_instances(route_info, make_service([healthy, open_instance]))
    assert result.instances == [healthy, open_instance]
