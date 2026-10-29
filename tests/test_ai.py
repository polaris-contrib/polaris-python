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

"""Exercise ordinary instance snapshots, service contracts and Skill RPCs."""

import asyncio
import copy
import io
import threading
import zipfile
from dataclasses import replace

import grpc
import pytest
from polarismesh_specification.api.v1.service_manage import grpcapi_pb2_grpc, response_pb2, service_pb2
from polarismesh_specification.api.v1.skill_manage import skill_service_pb2 as skill_pb, skill_service_pb2_grpc

from polaris import Configuration, ConsumerAPI, Instance, ProviderAPI, ServiceWatch, SkillAPI, init_context_by_config
from polaris.pkg.model.contract import GetServiceContractRequest, ServiceContract, ServiceFeature, ServiceFeatureType
from polaris.pkg.model.core import EventType, ServiceEventKey
from polaris.pkg.model.event import SDKEventName, SDKEventType, now_event
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.pkg.model.server import InstanceDeRegisterRequest, InstanceRegisterRequest
from polaris.pkg.model.rule import GetServiceRuleRequest
from polaris.pkg.model.service import (GetAllInstancesRequest, GetHealthyInstancesRequest,
                                       GetInstancesRequest, GetOneInstanceRequest, ServiceInstances,
                                       ServiceStatus, ServiceType)
from polaris.pkg.model.skill import SkillDownloadRequest, SkillGetRequest, SkillListRequest
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection


class RegistryStub:
    """Replace only RPC boundaries while preserving SDK scheduling and persistence."""

    def __init__(self):
        self.calls = []
        self.instances = []
        self.service_status = ServiceStatus.NORMAL
        self.contract = None
        self.contract_error = False
        self.skill_error = None
        self.download_parts = None
        self.skill_version = "v1"
        self.revision = 0

    def record(self, method, request, metadata):
        self.calls.append((method, request, metadata, threading.get_ident()))

    async def ReportClient(self, request, timeout=None, metadata=()):
        self.record("ReportClient", request, metadata)
        return response_pb2.Response(code={"value": 200000})

    def Discover(self, requests, timeout=None, metadata=()):
        async def responses():
            async for request in requests:
                self.record("Discover", request, metadata)
                self.revision += 1
                yield response_pb2.DiscoverResponse(
                    code={"value": 200000}, type=request.type,
                    service=service_pb2.Service(name=request.service.name, namespace=request.service.namespace,
                                               revision={"value": str(self.revision)}, service_type=ServiceType.MCP_SERVER,
                                               service_status=self.service_status,
                                               extended_metadata=[{"type": 1, "agent_skill": {"name": "lookup", "version": "v1"}}]),
                    instances=self.instances,
                )
        return responses()

    async def RegisterInstance(self, request, timeout=None, metadata=()):
        self.record("RegisterInstance", request, metadata)
        result = service_pb2.Instance()
        result.CopyFrom(request)
        result.id.value = "registered"
        self.instances = [result]
        return response_pb2.Response(code={"value": 200000}, instance=result)

    async def Heartbeat(self, request, timeout=None, metadata=()):
        self.record("Heartbeat", request, metadata)
        return response_pb2.Response(code={"value": 200000})

    async def DeregisterInstance(self, request, timeout=None, metadata=()):
        self.record("DeregisterInstance", request, metadata)
        self.instances = []
        return response_pb2.Response(code={"value": 200000})

    async def ReportServiceContract(self, request, timeout=None, metadata=()):
        self.record("ReportServiceContract", request, metadata)
        self.contract = request
        return response_pb2.Response(code={"value": 500000 if self.contract_error else 200000})

    async def GetServiceContract(self, request, timeout=None, metadata=()):
        self.record("GetServiceContract", request, metadata)
        return response_pb2.Response(code={"value": 200000}, serviceContract=self.contract)

    def _skill_check(self):
        if self.skill_error:
            raise self.skill_error

    async def GetSkill(self, request, timeout=None, metadata=()):
        self.record("GetSkill", request, metadata)
        self._skill_check()
        version = request.version or self.skill_version
        return skill_pb.GetSkillResponse(code=200000, content="# lookup",
                                         resource={"name": request.name, "namespace": request.namespace,
                                                   "tags": ["search"], "version_info": {"active_version": version}},
                                         version={"name": request.name, "namespace": request.namespace, "version": version})

    async def GetSkillList(self, request, timeout=None, metadata=()):
        self.record("GetSkillList", request, metadata)
        self._skill_check()
        return skill_pb.ListSkillsResponse(code=200000, total=1,
                                            resources=[{"name": "lookup", "namespace": "ns", "tags": ["search"]}])

    def DownloadSkill(self, request, timeout=None, metadata=()):
        self.record("DownloadSkill", request, metadata)
        async def responses():
            self._skill_check()
            if self.download_parts is not None:
                for part in self.download_parts:
                    if isinstance(part, Exception):
                        raise part
                    yield part
            elif request.format == "zip":
                yield skill_pb.DownloadSkillResponse(code=200000, version=request.version or self.skill_version,
                                                      content_type="application/zip", zip_chunk=b"PK", total_size=4,
                                                      filename="lookup.zip")
                yield skill_pb.DownloadSkillResponse(code=0, zip_chunk=b"34")
            else:
                yield skill_pb.DownloadSkillResponse(code=200000, version=request.version or self.skill_version,
                                                      content_type="text/markdown", content="# lookup", total_size=8)
        return responses()


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    stub = RegistryStub()
    async def fake_stub(connection, address):
        return stub
    monkeypatch.setattr(GrpcConnection, "_stub", fake_stub)
    config = Configuration.from_dict({
        "global": {"api": {"bindIP": "127.0.0.1"}, "serverConnector": {"addresses": ["registry:8091"]}},
        "ai": {"skill": {"serverConnector": {"addresses": ["skill:8094"], "token": "skill-token",
                                                "persistDir": str(tmp_path / "skills"), "persistRetryInterval": "1ms"}}},
    }, apply_env=False)
    contexts = []
    def create():
        context = init_context_by_config(config)
        contexts.append(context)
        return context
    context = create()
    yield stub, context, create
    for item in contexts:
        item.destroy()


def instance(id="node", port=8080, **kwargs):
    return service_pb2.Instance(id={"value": id}, host={"value": "127.0.0.1"}, port={"value": port},
                                weight={"value": 100}, healthy={"value": True},
                                protocol={"value": "mcp-streamable-http"}, version={"value": "v1"},
                                metadata={"mcp-server-name": "mcp", "mcp-protocol-version": "2025-03-26,2025-06-18"},
                                **kwargs)


def registration():
    return InstanceRegisterRequest(namespace="ns", service="mcp", service_token="token", host="127.0.0.1", port=8080,
                                   ttl=1, protocol="mcp-streamable-http", version="v1",
                                   metadata={"mcp-server-name": "mcp", "mcp-protocol-version": "2025-06-18",
                                             "mcp-endpoint-path": "/mcp"})


def test_snapshot_keeps_all_instances_sorted_and_isolates_response_mutation():
    isolated = instance("isolated", 8081, isolate={"value": True})
    zero = instance("zero", 8082)
    zero.weight.value = 0
    response = response_pb2.DiscoverResponse(service={"name": {"value": "mcp"}, "namespace": {"value": "ns"},
                                                        "service_type": ServiceType.MCP_SERVER,
                                                        "extended_metadata": [{"type": 1, "agent_skill": {"name": "lookup", "version": "v1"}}]},
                                             instances=[zero, instance(), isolated])
    snapshot = ServiceInstances.new_from_discover_rsp(response)
    response.instances[1].host.value = "changed"
    assert [item.get_id() for item in snapshot.instances] == ["node", "isolated", "zero"]
    assert snapshot.total_weight == 200
    assert snapshot.instances[0].get_host() == "127.0.0.1"
    assert snapshot.get_service_type() == ServiceType.MCP_SERVER
    assert snapshot.get_extended_metadata()[0].agent_skill.version == "v1"
    assert all(type(item) is Instance for item in snapshot.instances)


def test_snapshot_reuses_same_id_local_value_and_defaults_missing_weight():
    response = response_pb2.DiscoverResponse(service={"name": {"value": "mcp"}, "namespace": {"value": "ns"}},
                                             instances=[instance()])
    old = ServiceInstances.new_from_discover_rsp(response)
    response.instances[0].ClearField("weight")
    fresh = ServiceInstances.new_from_discover_rsp(response, old_instances=old)
    assert fresh.instances[0].get_local_value() is old.instances[0].get_local_value()
    assert fresh.instances[0].get_weight() == 100


@pytest.mark.asyncio
async def test_public_service_list_watch_filters_events_and_pins_cache(runtime):
    stub, context, _ = runtime
    stub.instances = [instance()]
    consumer = ConsumerAPI(context)
    request = GetInstancesRequest(namespace="ns", service="mcp")
    snapshot = await consumer.async_get_all_instances(request)
    assert len(snapshot.get_instances()) == 1
    assert ServiceEventKey("ns", "mcp", EventType.Instance) in await consumer.async_get_services()

    events = []
    watch = await consumer.async_watch_service(request, events.append)
    assert isinstance(watch, ServiceWatch)
    cache_key = ServiceEventKey("ns", "mcp", EventType.Instance)
    cache_obj = context.get_engine().registry.service_map[cache_key]
    cache_obj.last_visit_time = 0
    await context.get_engine().registry.expire_services()
    assert context.get_engine().registry.service_map.get(cache_key) is cache_obj

    event_center = context.get_event_center()
    event_center.publish(now_event(
        context.get_client_id(), SDKEventType.INSTANCE, SDKEventName.ON_SERVICE_UPDATED,
        namespace="other", service="mcp",
    ))
    event_center.publish(now_event(
        context.get_client_id(), SDKEventType.CIRCUIT_BREAKING,
        SDKEventName.CIRCUIT_BREAKER_OPEN, namespace="ns", service="mcp",
    ))
    event_center.publish(now_event(
        context.get_client_id(), SDKEventType.INSTANCE, SDKEventName.ON_SERVICE_UPDATED,
        namespace="ns", service="mcp",
    ))
    assert len(events) == 1
    assert events[0].event_name == SDKEventName.ON_SERVICE_UPDATED

    watch.close()
    assert watch._closed
    cache_obj.last_visit_time = 0
    await context.get_engine().registry.expire_services()
    assert context.get_engine().registry.service_map.get(cache_key) is None


def test_route_rule_sync_and_async_names_are_explicit(runtime):
    _, context, _ = runtime
    consumer = ConsumerAPI(context)
    request = GetServiceRuleRequest(namespace="ns", service="mcp")
    with pytest.raises(SDKError, match="only instance resources"):
        consumer.get_route_rule(request)


@pytest.mark.asyncio
async def test_provider_registers_mcp_as_ordinary_instance_and_contract_is_separate(runtime):
    stub, context, _ = runtime
    api = ProviderAPI(context)
    assert (await api.async_register_instance(registration())).instance_id == "registered"
    assert not any(call[0] in ("Discover", "ReportServiceContract") for call in stub.calls)
    await api.async_report_service_contract(ServiceContract(
        "ns", "mcp", protocol="mcp-streamable-http", version="v1",
        service_features=[ServiceFeature(kind, name) for kind, name in zip(
            ServiceFeatureType, ("lookup", "document", "summarize"))],
    ))
    await asyncio.sleep(1.05)
    methods = [call[0] for call in stub.calls]
    assert methods.count("ReportServiceContract") == 1
    assert "Heartbeat" in methods
    assert [item.type for item in stub.contract.service_features] == list(ServiceFeatureType)
    assert all(item.status == 0 for item in stub.contract.service_features)
    request = next(call[1] for call in stub.calls if call[0] == "RegisterInstance")
    assert request.metadata["mcp-server-name"] == "mcp"
    assert request.metadata["mcp-endpoint-path"] == "/mcp"
    assert request.version.value == "v1"
    await api.async_deregister(InstanceDeRegisterRequest(
        namespace="ns", service="mcp", service_token="token", host="127.0.0.1", port=8080, instance_id="registered",
    ))
    assert [call[0] for call in stub.calls].count("DeregisterInstance") == 1
    assert not context.is_destroy()
    assert not context.engine.register_states._states
    assert len({call[3] for call in stub.calls}) == 1


def test_provider_context_shutdown_stops_heartbeat_without_implicit_mcp_deregistration(runtime):
    stub, context, _ = runtime
    api = ProviderAPI(context)
    api.register_instance(registration())
    context.destroy()
    assert not any(call[0] == "DeregisterInstance" for call in stub.calls)
    assert stub.instances
    assert not context.engine.register_states._states
    assert not context.engine.thread.is_alive()


def test_provider_contract_failure_does_not_change_instance_registration(runtime):
    stub, context, _ = runtime
    stub.contract_error = True
    api = ProviderAPI(context)
    response = api.register_instance(registration())
    assert response.instance_id == "registered"
    with pytest.raises(SDKError):
        api.report_service_contract(ServiceContract("ns", "mcp", protocol="mcp-streamable-http"))
    assert len(context.engine.register_states._states) == 1


@pytest.mark.asyncio
async def test_consumer_keeps_all_mcp_instances_and_uses_ordinary_routing(runtime):
    stub, context, _ = runtime
    good = instance()
    isolated = instance("isolated", 8081, isolate={"value": True})
    bad = instance("unhealthy", 8082)
    bad.healthy.value = False
    zero = instance("zero", 8083)
    zero.weight.value = 0
    other = instance("other-version", 8084)
    other.version.value = "v2"
    stub.instances = [zero, bad, other, isolated, good]
    api = ConsumerAPI(context)
    request = GetInstancesRequest(namespace="ns", service="mcp")
    response = await api.async_get_all_instances(request)
    assert len(response.instances) == 5
    selected = await api.async_get_one_instance(GetOneInstanceRequest(namespace="ns", service="mcp"))
    assert type(selected) is Instance and selected.get_id() in ("node", "other-version")
    cached = context.engine.registry.service_map
    assert len(next(iter(cached.values())).value.instances) == 5
    assert all(key.event_type == EventType.Instance for key in cached)


@pytest.mark.asyncio
async def test_consumer_exposes_service_status_without_mcp_specific_filtering(runtime):
    stub, context, _ = runtime
    stub.instances = [instance()]
    stub.service_status = ServiceStatus.OFFLINE
    response = await ConsumerAPI(context).async_get_all_instances(GetInstancesRequest(namespace="ns", service="mcp"))
    assert response.get_service_status() == ServiceStatus.OFFLINE
    assert len(response.instances) == 1


@pytest.mark.asyncio
async def test_offline_service_can_be_excluded_from_filtered_discovery(runtime):
    stub, context, _ = runtime
    stub.instances = [instance()]
    stub.service_status = ServiceStatus.OFFLINE
    api = ConsumerAPI(context)

    default = await api.async_get_instances(GetInstancesRequest(namespace="ns", service="mcp"))
    assert len(default.instances) == 1
    request = GetInstancesRequest(namespace="ns", service="mcp", exclude_offline_service=True)
    candidates = await api.async_get_instances(request)
    healthy = await api.async_get_healthy_instances(GetHealthyInstancesRequest(
        namespace="ns", service="mcp", exclude_offline_service=True))
    assert candidates.instances == healthy.instances == []
    with pytest.raises(SDKError, match="not found for load balance"):
        await api.async_get_one_instance(GetOneInstanceRequest(
            namespace="ns", service="mcp", exclude_offline_service=True))
    full = await api.async_get_all_instances(GetAllInstancesRequest(
        namespace="ns", service="mcp", exclude_offline_service=True))
    assert len(full.instances) == 1 and full.get_service_status() == ServiceStatus.OFFLINE

    invalid = GetInstancesRequest(namespace="ns", service="mcp", exclude_offline_service="yes")
    with pytest.raises(SDKError):
        invalid.validate()


def mounted_service(*skills):
    return ServiceInstances(service=service_pb2.Service(
        namespace={"value": "ns"}, name={"value": "agent"},
        extended_metadata=[{"type": 1, "agent_skill": {"name": name, "version": version}}
                           for name, version in skills]))


@pytest.mark.parametrize("mount_version, requested_version, expected", [
    ("mounted", "caller", "mounted"),
    ("", "caller", "caller"),
    ("", "", ""),
])
def test_mounted_skill_version_priority(runtime, mount_version, requested_version, expected):
    _, context, _ = runtime
    api = SkillAPI(context)
    request = api.resolve_mounted_skill_request(
        mounted_service(("lookup", mount_version)), requested_version=requested_version, timeout=17)
    assert request == SkillGetRequest("ns", "lookup", expected, 17)


def test_mounted_skill_selection_requires_unique_match(runtime):
    _, context, _ = runtime
    api = SkillAPI(context)
    snapshot = mounted_service(("first", "v1"), ("second", "v2"))
    with pytest.raises(SDKError, match="specify skill_name"):
        api.resolve_mounted_skill_request(snapshot)
    request = api.resolve_mounted_skill_request(snapshot, skill_name="second")
    assert request.name == "second" and request.version == "v2"
    with pytest.raises(SDKError, match="no matching"):
        api.resolve_mounted_skill_request(mounted_service(), skill_name="missing")


@pytest.mark.asyncio
async def test_mounted_skill_get_and_download_use_resolved_version(runtime):
    stub, context, _ = runtime
    api = SkillAPI(context)
    snapshot = mounted_service(("lookup", "mounted"))

    result = await api.async_get_mounted_skill(snapshot, requested_version="caller")
    package = await api.async_download_mounted_skill(snapshot, requested_version="caller", format="zip")
    assert result.version.version == package.version == "mounted"
    assert package.data == b"PK34"
    requests = [call[1] for call in stub.calls if call[0] in ("GetSkill", "DownloadSkill")]
    assert all(request.version == "mounted" for request in requests)


def test_sdk_has_no_mcp_api_factories_or_specialized_request_models():
    import importlib.util
    import polaris
    for name in ("MCPAPI", "create_mcp_by_config", "create_mcp_by_file", "mcp_endpoint"):
        assert not hasattr(polaris, name) and name not in polaris.__all__
    assert importlib.util.find_spec("polaris.api.mcp") is None
    assert importlib.util.find_spec("polaris.pkg.model.mcp") is None


@pytest.mark.asyncio
async def test_skill_get_list_download_and_separate_connection(runtime):
    stub, context, _ = runtime
    api = SkillAPI(context)
    skill = await api.async_get_skill(SkillGetRequest("ns", "lookup"))
    assert skill.content == "# lookup"
    assert skill.version.version == "v1"
    assert skill.resource.tags == ["search"]
    results = await api.async_list_skills(SkillListRequest(tag="search", keyword="lookup", offset=2, limit=5))
    assert results.total == 1
    request = next(call[1] for call in stub.calls if call[0] == "GetSkillList")
    assert (request.tag, request.keyword, request.offset, request.limit) == ("search", "lookup", 2, 5)
    package = await api.async_download_skill(SkillDownloadRequest("ns", "lookup", format="zip"))
    assert package.data == b"PK34" and package.total_size == 4
    assert context.engine.skill_connector.connection is not context.engine.svc_connector.connection
    assert context.engine.skill_connector.connection.settings.addresses == ["skill:8094"]
    for method, _, metadata, _ in stub.calls:
        if method in ("GetSkill", "GetSkillList", "DownloadSkill"):
            assert dict(metadata)["x-polaris-token"] == "skill-token"
            assert dict(metadata)["request-id"].startswith("1")
    api.destroy()
    assert not context.is_destroy()


def test_skill_sync_reads_and_restart_network_fallback(runtime):
    stub, context, create = runtime
    api = SkillAPI(context)
    assert api.get_skill(SkillGetRequest("ns", "lookup")).content == "# lookup"
    assert api.download_skill(SkillDownloadRequest("ns", "lookup", format="zip")).data == b"PK34"
    context.destroy()
    stub.skill_error = SDKError(ErrorCode.ErrCodeNetworkError, "offline")
    restarted = create()
    reader = SkillAPI(restarted)
    content = reader.get_skill(SkillGetRequest("ns", "lookup"))
    package = reader.download_skill(SkillDownloadRequest("ns", "lookup", format="zip"))
    assert content.loaded_from_file and content.version.version == "v1"
    assert package.loaded_from_file and package.data == b"PK34"
    with pytest.raises(SDKError, match="offline"):
        reader.list_skills(SkillListRequest())
    with pytest.raises(SDKError, match="offline"):
        reader.get_skill(SkillGetRequest("ns", "lookup", version="v2"))
    with pytest.raises(SDKError, match="offline"):
        reader.get_skill(SkillGetRequest("other", "lookup"))


@pytest.mark.asyncio
async def test_skill_server_errors_do_not_fallback(runtime):
    stub, context, _ = runtime
    api = SkillAPI(context)
    await api.async_get_skill(SkillGetRequest("ns", "lookup"))
    stub.skill_error = SDKError(ErrorCode.ErrCodeServerError, "permission denied", server_code=401000)
    with pytest.raises(SDKError, match="permission denied"):
        await api.async_get_skill(SkillGetRequest("ns", "lookup"))


@pytest.mark.asyncio
@pytest.mark.parametrize("parts", [[], [skill_pb.DownloadSkillResponse(code=200000, version="v1", zip_chunk=b"PK", total_size=3)],
                                   [skill_pb.DownloadSkillResponse(code=200000, version="v1"),
                                    skill_pb.DownloadSkillResponse(code=200000, version="v2")]])
async def test_skill_invalid_or_incomplete_download_is_rejected(runtime, parts):
    stub, context, _ = runtime
    stub.download_parts = parts
    with pytest.raises(SDKError) as raised:
        await SkillAPI(context).async_download_skill(SkillDownloadRequest("ns", "lookup", format="zip"))
    assert raised.value.err_code == ErrorCode.ErrCodeInvalidResponse


@pytest.mark.asyncio
async def test_skill_partial_stream_retry_discards_old_bytes(runtime):
    stub, context, _ = runtime
    original = stub.DownloadSkill
    attempts = 0
    def download(request, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            return original(request, **kwargs)
        async def incomplete():
            yield skill_pb.DownloadSkillResponse(code=200000, version="v1", zip_chunk=b"partial", total_size=20)
            raise grpc.aio.AioRpcError(grpc.StatusCode.UNAVAILABLE, (), (), "disconnected")
        return incomplete()
    stub.DownloadSkill = download
    context.engine.skill_connector.connection.settings = replace(
        context.engine.skill_connector.connection.settings, retry_backoff_seconds=0,
    )
    result = await SkillAPI(context).async_download_skill(SkillDownloadRequest("ns", "lookup", format="zip"))
    assert result.data == b"PK34" and attempts == 2


@pytest.mark.asyncio
async def test_contract_sync_and_async_conversion(runtime):
    stub, context, _ = runtime
    from polaris.api.provider import ProviderAPI
    request = ServiceContract("ns", "mcp", protocol="mcp-streamable-http", version="v1",
                               service_features=[ServiceFeature(ServiceFeatureType.MCP_TOOL, "lookup")])
    await ProviderAPI(context).async_report_service_contract(request)
    result = await ConsumerAPI(context).async_get_service_contract(GetServiceContractRequest("ns", "mcp"))
    assert result.service_features[0].name == "lookup"
    assert result.protocol == "mcp-streamable-http"


@pytest.mark.asyncio
async def test_new_apis_reject_sync_calls_in_event_loop_and_destroyed_context(runtime):
    stub, context, _ = runtime
    api = SkillAPI(context)
    with pytest.raises(SDKError, match="active event loop"):
        api.get_skill(SkillGetRequest("ns", "lookup"))
    context.destroy()
    with pytest.raises(SDKError):
        await api.async_get_skill(SkillGetRequest("ns", "lookup"))


def test_skill_yaml_and_code_assignments_produce_isolated_configurations():
    config = Configuration.from_dict({"ai": {"skill": {"serverConnector": {
        "addresses": ["skill:8094"], "messageTimeout": "2s", "downloadTimeout": "10s",
        "persistRetryInterval": "100ms", "persistEnable": False,
    }}}}, apply_env=False)
    config.set_default()
    connector = config.get_ai().get_skill().get_server_connector()
    assert (connector.message_timeout, connector.download_timeout, connector.persist_retry_interval) == (2000, 10000, 100)
    connector.download_timeout = 9000
    config.verify()
    assert connector.download_timeout == 9000 and not connector.persist_enable


def test_skill_file_factory_loads_polaris_yaml_and_owns_context(runtime, tmp_path):
    _, context, _ = runtime
    from polaris import create_skill_by_file
    file = tmp_path / "polaris.yaml"
    file.write_text(
        "global:\n  api:\n    bindIP: 127.0.0.1\n"
        "consumer:\n  localCache:\n    persistDir: " + str(tmp_path / "file-instances") + "\n"
        "ai:\n  skill:\n    serverConnector:\n      addresses: [file-skill:8094]\n"
        "      messageTimeout: 2s\n      downloadTimeout: 10s\n      persistEnable: false\n"
    )
    api = create_skill_by_file(str(file))
    try:
        connection = api.context.engine.skill_connector.connection
        assert connection.settings.addresses == ["file-skill:8094"]
        assert connection.settings.timeout_seconds == 2
        assert api.get_skill(SkillGetRequest("ns", "lookup")).content == "# lookup"
        assert api.context.engine.skill_flow.persistence is None
    finally:
        api.destroy()
    assert api.context.is_destroy() and not context.is_destroy()




def test_skill_contexts_keep_connections_backups_and_lifecycle_isolated(runtime, tmp_path):
    stub, first, _ = runtime
    config = copy.deepcopy(first.get_config())
    config.get_ai().get_skill().get_server_connector().persist_dir = str(tmp_path / "other-skills")
    config.get_ai().get_skill().get_server_connector().token = "other-token"
    second = init_context_by_config(config)
    try:
        first_api, second_api = SkillAPI(first), SkillAPI(second)
        assert first_api.get_skill(SkillGetRequest("ns", "lookup")).version.version == "v1"
        stub.skill_version = "v2"
        assert second_api.get_skill(SkillGetRequest("ns", "lookup")).version.version == "v2"
        first_cache = first.engine.skill_flow.persistence
        second_cache = second.engine.skill_flow.persistence
        assert first_cache.base_dir != second_cache.base_dir
        assert first_cache.write_thread is not second_cache.write_thread
        assert first.engine.skill_connector.connection.settings.token == "skill-token"
        first.destroy()
        assert not first_cache.write_thread.is_alive() and first_cache.lock_file.closed
        assert first.engine.skill_connector.connection._closed
        assert not second.is_destroy() and not second.engine.skill_connector.connection._closed
        assert second_api.get_skill(SkillGetRequest("ns", "lookup")).version.version == "v2"
    finally:
        second.destroy()


def test_skill_disabled_persistence_does_not_load_or_create_backup(runtime):
    stub, context, _ = runtime
    context.get_config().get_ai().get_skill().get_server_connector().persist_enable = False
    api = SkillAPI(context)
    assert api.get_skill(SkillGetRequest("ns", "lookup")).content == "# lookup"
    assert context.engine.skill_flow.persistence is None
    stub.skill_error = SDKError(ErrorCode.ErrCodeNetworkError, "offline")
    with pytest.raises(SDKError, match="offline"):
        api.get_skill(SkillGetRequest("ns", "lookup"))


def test_skill_unusable_backup_directory_keeps_remote_reads_available(runtime, tmp_path):
    _, context, _ = runtime
    invalid = tmp_path / "not-a-directory"
    invalid.write_text("occupied")
    context.get_config().get_ai().get_skill().get_server_connector().persist_dir = str(invalid)
    assert SkillAPI(context).get_skill(SkillGetRequest("ns", "lookup")).content == "# lookup"
    assert context.engine.skill_flow.persistence is None


def test_skill_zero_success_code_is_persisted_and_reloaded(runtime):
    stub, context, create = runtime
    original = stub.GetSkill

    async def zero_success(*args, **kwargs):
        response = await original(*args, **kwargs)
        response.code = 0
        return response

    stub.GetSkill = zero_success
    response = SkillAPI(context).get_skill(SkillGetRequest("ns", "lookup"))
    assert response.code == 0
    context.destroy()
    stub.skill_error = SDKError(ErrorCode.ErrCodeNetworkError, "offline")
    response = SkillAPI(create()).get_skill(SkillGetRequest("ns", "lookup"))
    assert response.code == 0 and response.loaded_from_file


@pytest.mark.asyncio
async def test_skill_versioned_backup_active_pointer_and_configured_retries(runtime, monkeypatch):
    stub, context, _ = runtime
    config = context.get_config().get_ai().get_skill().get_server_connector()
    config.persist_max_read_retry = 2
    config.persist_max_write_retry = 2
    api = SkillAPI(context)
    await api.async_get_skill(SkillGetRequest("ns", "lookup", version="v0"))
    persistence = context.engine.skill_flow.persistence
    assert (persistence.max_read_retry, persistence.max_write_retry) == (2, 2)
    from polaris.plugin.skill.persistence import SkillCacheKey
    await asyncio.to_thread(persistence.queue.join)
    assert await persistence.async_get(SkillCacheKey("ns", "lookup", "", "active"), expire=None) is None

    attempts = 0
    original_save = persistence._save

    def transient_write(key, response):
        nonlocal attempts
        if key.operation == "get":
            attempts += 1
            if attempts <= 2:
                raise OSError("temporary write failure")
        return original_save(key, response)

    monkeypatch.setattr(persistence, "_save", transient_write)
    await api.async_get_skill(SkillGetRequest("ns", "lookup"))
    await asyncio.to_thread(persistence.queue.join)
    assert attempts == 3
    stub.skill_version = "v2"
    await api.async_get_skill(SkillGetRequest("ns", "lookup"))
    await asyncio.to_thread(persistence.queue.join)
    assert (await persistence.load(SkillGetRequest("ns", "lookup"), "get")).version.version == "v2"
    assert (await persistence.load(SkillGetRequest("ns", "lookup", version="v1"), "get")).version.version == "v1"

    reads = 0
    original_read = persistence._read

    def transient_read(key, expire):
        nonlocal reads
        reads += 1
        if reads <= 2:
            raise OSError("temporary read failure")
        return original_read(key, expire)

    monkeypatch.setattr(persistence, "_read", transient_read)
    assert (await persistence.load(SkillGetRequest("ns", "lookup", version="v1"), "get")).content == "# lookup"
    assert reads == 3


@pytest.mark.asyncio
async def test_skill_corrupt_backup_never_returns_as_success(runtime):
    stub, context, _ = runtime
    api = SkillAPI(context)
    await api.async_get_skill(SkillGetRequest("ns", "lookup"))
    persistence = context.engine.skill_flow.persistence
    await asyncio.to_thread(persistence.queue.join)
    from pathlib import Path
    from polaris.plugin.skill.persistence import SkillCacheKey
    Path(persistence.get_cache_file_path(SkillCacheKey("ns", "lookup", "v1", "get"))).write_text("broken JSON")
    stub.skill_error = SDKError(ErrorCode.ErrCodeNetworkError, "offline")
    with pytest.raises(SDKError, match="offline"):
        await api.async_get_skill(SkillGetRequest("ns", "lookup"))


def test_factory_owned_skill_api_closes_context(runtime):
    _, context, _ = runtime
    from polaris import create_skill_by_config
    api = create_skill_by_config(context.get_config())
    try:
        api.get_skill(SkillGetRequest("ns", "lookup"))
    finally:
        api.destroy()
    assert api.context.is_destroy() and not api.context.engine.thread.is_alive()


@pytest.mark.asyncio
async def test_skill_and_contract_generated_stubs_use_separate_real_grpc_channels(tmp_path):
    calls = []
    contract = None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", "# lookup")
    package = buffer.getvalue()

    class RegistryServer(grpcapi_pb2_grpc.PolarisGRPCServicer,
                         grpcapi_pb2_grpc.PolarisServiceContractGRPCServicer):
        async def ReportClient(self, request, context):
            return response_pb2.Response(code={"value": 200000})

        async def ReportServiceContract(self, request, context):
            nonlocal contract
            calls.append(("contract", dict(context.invocation_metadata())))
            contract = request
            return response_pb2.Response(code={"value": 200000})

        async def GetServiceContract(self, request, context):
            return response_pb2.Response(code={"value": 200000}, serviceContract=contract)

    class SkillServer(skill_service_pb2_grpc.PolarisSkillServicer):
        async def GetSkill(self, request, context):
            calls.append(("skill", dict(context.invocation_metadata())))
            return skill_pb.GetSkillResponse(code=200000, content="# lookup",
                                            resource={"name": request.name, "namespace": request.namespace},
                                            version={"version": request.version or "v1"})

        async def GetSkillList(self, request, context):
            return skill_pb.ListSkillsResponse(code=200000, total=1,
                                              resources=[{"name": "lookup", "namespace": "ns"}])

        async def DownloadSkill(self, request, context):
            yield skill_pb.DownloadSkillResponse(code=200000, version="v1", total_size=len(package),
                                                content_type="application/zip", zip_chunk=package[:20])
            yield skill_pb.DownloadSkillResponse(zip_chunk=package[20:])

    registry_server, skill_server = grpc.aio.server(), grpc.aio.server()
    registry = RegistryServer()
    grpcapi_pb2_grpc.add_PolarisGRPCServicer_to_server(registry, registry_server)
    grpcapi_pb2_grpc.add_PolarisServiceContractGRPCServicer_to_server(registry, registry_server)
    skill_service_pb2_grpc.add_PolarisSkillServicer_to_server(SkillServer(), skill_server)
    registry_port = registry_server.add_insecure_port("127.0.0.1:0")
    skill_port = skill_server.add_insecure_port("127.0.0.1:0")
    await registry_server.start()
    await skill_server.start()
    context = None
    try:
        config = Configuration.from_dict({
            "global": {"api": {"bindIP": "127.0.0.1"}, "serverConnector": {
                "addresses": [f"127.0.0.1:{registry_port}"], "token": "registry-token"}},
            "consumer": {"localCache": {"persistDir": str(tmp_path / "instances")}},
            "ai": {"skill": {"serverConnector": {"addresses": [f"127.0.0.1:{skill_port}"],
                                                   "token": "skill-token", "persistDir": str(tmp_path / "skills")}}},
        }, apply_env=False)
        context = init_context_by_config(config)
        from polaris.api.provider import ProviderAPI
        await ProviderAPI(context).async_report_service_contract(ServiceContract("ns", "mcp", protocol="mcp-sse"))
        received = await ConsumerAPI(context).async_get_service_contract(GetServiceContractRequest("ns", "mcp"))
        assert received.protocol == "mcp-sse"
        api = SkillAPI(context)
        assert (await api.async_get_skill(SkillGetRequest("ns", "lookup"))).content == "# lookup"
        assert (await api.async_list_skills(SkillListRequest(namespace="ns"))).total == 1
        download = await api.async_download_skill(SkillDownloadRequest("ns", "lookup", format="zip"))
        assert download.data == package
        for kind, metadata in calls:
            assert metadata["x-polaris-token"] == ("skill-token" if kind == "skill" else "registry-token")
            assert metadata["request-id"].startswith("1" if kind == "skill" else "5")
        instance_connection = context.engine.svc_connector.connection
        skill_connection = context.engine.skill_connector.connection
        assert set(instance_connection._channels) == {f"127.0.0.1:{registry_port}"}
        assert set(skill_connection._channels) == {f"127.0.0.1:{skill_port}"}
        assert instance_connection._contract_stubs
    finally:
        if context is not None:
            await asyncio.to_thread(context.destroy)
        await registry_server.stop(None)
        await skill_server.stop(None)
