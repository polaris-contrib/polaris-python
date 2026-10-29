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

"""Verify application-owned MCP policies and cleanup using ordinary SDK APIs."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

from examples._internal._ai_stub import AIStub
from examples.mcp import main as demo
from polaris import Instance, LogOptions
from polaris.pkg.model.core import ServiceKey
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection


def node(protocol="mcp-streamable-http", versions="2025-06-18", **fields):
    return Instance(service_pb2.Instance(
        id={"value": "existing"}, host={"value": "127.0.0.1"}, port={"value": 18080},
        healthy={"value": True}, weight={"value": 100}, protocol={"value": protocol},
        metadata={"mcp-protocol-version": versions}, **fields,
    ), ServiceKey("ns", "mcp"))


def arguments(**values):
    return SimpleNamespace(namespace="ns", service="mcp", timeout=500,
                           protocol=values.get("protocol", "mcp-streamable-http"),
                           protocol_version=values.get("protocol_version", "2025-06-18"),
                           strict_compatible=values.get("strict_compatible", False))


def consumer_for(*instances):
    consumer = Mock()
    consumer.get_all_instances.return_value.instances = list(instances)
    return consumer


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    stub = AIStub()
    contexts = []
    warnings = []
    initialize = demo.init_context_by_config

    async def fake_stub(connection, address):
        return stub

    def create(config, **kwargs):
        config.get_consumer().get_local_cache().service_refresh_interval = 10
        context = initialize(config, **kwargs)
        contexts.append(context)
        logger = context.get_value_context().logger
        logger.warning = Mock(wraps=logger.warning)
        warnings.append(logger.warning)
        return context

    monkeypatch.setattr(GrpcConnection, "_stub", fake_stub)
    monkeypatch.setattr(demo, "init_context_by_config", create)
    monkeypatch.setattr(demo, "demo_backup_directory", lambda entry: tmp_path / "backup")
    monkeypatch.setattr(demo, "demo_log_options", lambda entry: LogOptions(log_dir=tmp_path / "logs"))
    monkeypatch.setenv("POLARIS_E2E", "1")
    monkeypatch.delenv("POLARIS_TOKEN", raising=False)
    yield stub, contexts, warnings
    for context in contexts:
        context.destroy()


def run_example(*options):
    return demo.main(["--server", "offline:8091", "--namespace", "ns", "--service", "mcp",
                      "--host", "127.0.0.1", "--token", "token", "--timeout", "500",
                      "--wait", "0", *options])


def assert_destroyed(contexts):
    assert len(contexts) == 1
    context = contexts[0]
    assert context.is_destroy() and not context.engine.thread.is_alive()
    assert not context.engine.register_states._states
    assert context.engine.svc_connector.connection._closed


@pytest.mark.parametrize("protocol, path", [("mcp-streamable-http", "/mcp"), ("mcp-sse", "/sse")])
def test_example_ordinary_provider_consumer_roundtrip(runtime, capsys, protocol, path):
    stub, contexts, _ = runtime
    assert run_example("--protocol", protocol) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"instance_id": "mcp-node", "instance_type": "Instance",
                      "endpoint": f"http://127.0.0.1:18080{path}", "instances": ["mcp-node"],
                      "features": ["lookup", "document", "summarize"],
                      "host": "127.0.0.1", "port": 18080}
    methods = [method for method, _ in stub.calls]
    assert methods == ["register", "contract", "deregister"]
    registration = stub.calls[0][1]
    assert registration.protocol.value == protocol and registration.version.value == "v1"
    assert dict(registration.metadata) == {"mcp-server-name": "mcp", "mcp-protocol-version": "2025-06-18",
                                           "mcp-endpoint-path": path}
    assert [json.loads(item.content)["name"] for item in stub.contract.service_features] == result["features"]
    assert all(item.status == 0 for item in stub.contract.service_features)
    assert stub.calls[-1][1].id.value == "mcp-node" and not stub.instances
    assert_destroyed(contexts)


@pytest.mark.parametrize("method", ["RegisterInstance", "GetServiceContract", "DeregisterInstance"])
def test_example_rpc_failure_still_closes_context(runtime, monkeypatch, method):
    stub, contexts, _ = runtime
    failure = AsyncMock(return_value=response_pb2.Response(code={"value": 500000}))
    monkeypatch.setattr(stub, method, failure)
    with pytest.raises(SDKError):
        run_example()
    failure.assert_awaited_once()
    methods = [name for name, _ in stub.calls]
    if method == "RegisterInstance":
        assert "deregister" not in methods
    elif method == "GetServiceContract":
        assert methods[-1] == "deregister" and not stub.instances
    else:
        assert stub.instances
    assert_destroyed(contexts)


def test_example_contract_report_failure_warns_without_rolling_back_registration(runtime, monkeypatch, capsys):
    stub, contexts, warnings = runtime
    stub.contract = response_pb2.Response(serviceContract={"namespace": "ns", "service": "mcp"}).serviceContract
    monkeypatch.setattr(stub, "ReportServiceContract",
                        AsyncMock(return_value=response_pb2.Response(code={"value": 500000})))
    assert run_example() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["instance_id"] == "mcp-node" and result["features"] == []
    assert [method for method, _ in stub.calls] == ["register", "deregister"]
    assert any("startup contract report failed" in call.args[0] for call in warnings[0].call_args_list)
    assert_destroyed(contexts)


def test_example_strict_mismatch_does_not_register_and_closes_context(runtime):
    stub, contexts, _ = runtime
    stub.instances = [node(protocol="mcp-sse").instance]
    with pytest.raises(SDKError, match="transport mismatch"):
        run_example("--strict-compatible")
    assert not stub.calls
    assert_destroyed(contexts)


def test_example_non_strict_mismatch_warns_and_registers(runtime):
    stub, contexts, warnings = runtime
    stub.instances = [node(protocol="mcp-sse").instance]
    assert run_example() == 0
    assert [method for method, _ in stub.calls] == ["register", "contract", "deregister"]
    assert any("transport mismatch" in str(call.args) for call in warnings[0].call_args_list)
    assert_destroyed(contexts)


def test_example_selected_version_mismatch_still_deregisters(runtime, monkeypatch):
    stub, contexts, _ = runtime
    register = stub.RegisterInstance

    async def different_version(*args, **kwargs):
        result = await register(*args, **kwargs)
        stub.instances[0].version.value = "v2"
        return result

    monkeypatch.setattr(stub, "RegisterInstance", different_version)
    with pytest.raises(SDKError, match="does not match this MCP example"):
        run_example()
    assert [method for method, _ in stub.calls] == ["register", "contract", "deregister"]
    assert not stub.instances
    assert_destroyed(contexts)


@pytest.mark.parametrize("existing", [node(protocol="mcp-sse"), node(versions="2024-11-05")])
def test_compatibility_strict_mode_rejects_explicit_mismatch(existing):
    with pytest.raises(SDKError, match="mismatch|no intersection"):
        demo.check_compatible(consumer_for(existing), arguments(strict_compatible=True), Mock())


def test_compatibility_uses_first_eligible_instance_without_mutating_snapshot():
    isolated = node(protocol="mcp-sse", isolate={"value": True})
    unhealthy = node(protocol="mcp-sse")
    unhealthy.instance.healthy.value = False
    zero = node(protocol="mcp-sse")
    zero.instance.weight.value = 0
    valid = node(versions="2025-03-26, 2025-06-18")
    later = node(protocol="mcp-sse")
    original = [isolated, unhealthy, zero, valid, later]
    consumer = consumer_for(*original)
    logger = Mock()
    demo.check_compatible(consumer, arguments(strict_compatible=True), logger)
    logger.warning.assert_not_called()
    assert consumer.get_all_instances.return_value.instances == original


def test_compatibility_missing_protocol_version_does_not_reject_registration():
    existing = node()
    existing.instance.metadata.clear()
    logger = Mock()
    demo.check_compatible(consumer_for(existing), arguments(strict_compatible=True), logger)
    logger.warning.assert_not_called()


def test_compatibility_discovery_failure_warns_and_continues_even_in_strict_mode():
    consumer = Mock()
    failure = SDKError(ErrorCode.ErrCodeNetworkError, "offline")
    consumer.get_all_instances.side_effect = failure
    logger = Mock()
    demo.check_compatible(consumer, arguments(strict_compatible=True), logger)
    logger.warning.assert_called_once()
    assert logger.warning.call_args.args[1] is failure


@pytest.mark.parametrize("protocol, scheme, expected", [
    ("mcp-streamable-http", "http", "http://[::1]:18080/mcp"),
    ("mcp-sse", "https", "https://[::1]:18080/sse"),
])
def test_endpoint_ipv6_and_transport_default_path(protocol, scheme, expected):
    instance = node(protocol=protocol)
    instance.instance.host.value = "::1"
    assert demo.endpoint(instance, scheme=scheme) == expected


@pytest.mark.parametrize("path", ["relative", "//other-host", "/mcp?token=x", "/mcp#anchor"])
def test_endpoint_rejects_invalid_absolute_paths(path):
    instance = node()
    instance.instance.metadata["mcp-endpoint-path"] = path
    with pytest.raises(ValueError, match="absolute URL path"):
        demo.endpoint(instance)


@pytest.mark.parametrize("option", ["--protocol=stdio", "--path=//other-host", "--timeout=0", "--wait=-1",
                                  "--wait=nan", "--wait=inf", "--ttl=0"])
def test_main_rejects_invalid_options_before_creating_context(monkeypatch, option):
    initialize = Mock(side_effect=AssertionError("invalid arguments must not initialize the SDK"))
    monkeypatch.setattr(demo, "init_context_by_config", initialize)
    with pytest.raises(SystemExit) as error:
        demo.main([option])
    assert error.value.code == 2
    initialize.assert_not_called()
