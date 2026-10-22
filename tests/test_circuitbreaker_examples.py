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

"""HTTP/report mapping, fault controls and ownership in the circuit examples."""

import io
from http.client import IncompleteRead
from unittest.mock import AsyncMock, Mock
from urllib.error import HTTPError, URLError

import pytest
from polarismesh_specification.api.v1.service_manage import service_pb2

from examples.circuitbreaker.consumer import main as consumer
from examples.circuitbreaker.provider import main as provider
from polaris.pkg.model.core import ServiceKey
from polaris.pkg.model.server import InstanceRegisterRequest
from polaris.pkg.model.service import Instance, RetStatus


@pytest.fixture
def node():
    return Instance(service_pb2.Instance(id={"value": "example-instance"}, host={"value": "127.0.0.1"},
                    port={"value": 8080}, healthy={"value": True}), ServiceKey("default", "echo"))


def response(code, body=b"echo"):
    value = io.BytesIO(body)
    value.code = code
    return value


@pytest.mark.parametrize("code, expected", [(200, RetStatus.RetSuccess), (404, RetStatus.RetSuccess),
                                           (429, RetStatus.RetSuccess), (500, RetStatus.RetFail), (599, RetStatus.RetFail)])
def test_caller_reports_original_http_code_once(monkeypatch, node, code, expected):
    opener = Mock()
    if code >= 400:
        opener.open.side_effect = HTTPError("http://127.0.0.1:8080/echo", code, "status", {}, io.BytesIO(b"echo"))
    else:
        opener.open.return_value = response(code)
    monkeypatch.setattr(consumer, "build_opener", lambda *args: opener)
    api = Mock()
    api.get_one_instance.return_value = node
    outcome = consumer.CircuitBreakerCaller(api, "default", "echo").call("test-id")
    request = opener.open.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:8080/echo"
    assert request.get_header("X-request-id") == "test-id"
    assert outcome["instance_id"] == "example-instance" and outcome["body"] == "echo"
    assert outcome["ret_code"] == code and outcome["request_id"] == "test-id"
    api.sync_update_service_call_result.assert_called_once()
    report = api.sync_update_service_call_result.call_args.args[0]
    assert report.called_instance is node and report.ret_status == expected
    assert report.ret_code == code and report.delay >= 0


@pytest.mark.parametrize("error", [URLError("unreachable"), TimeoutError("timeout"), OSError("read failed")])
def test_caller_reports_transport_failure_as_minus_one(monkeypatch, node, error):
    opener = Mock()
    opener.open.side_effect = error
    monkeypatch.setattr(consumer, "build_opener", lambda *args: opener)
    api = Mock()
    outcome = consumer.CircuitBreakerCaller(api, "default", "echo").call_instance(node)
    assert outcome["ret_code"] == -1 and outcome["body"]
    api.sync_update_service_call_result.assert_called_once()
    assert api.sync_update_service_call_result.call_args.args[0].ret_status == RetStatus.RetFail


def test_caller_reports_truncated_response_as_transport_failure(monkeypatch, node):
    reply = Mock()
    reply.__enter__ = Mock(return_value=reply)
    reply.__exit__ = Mock(return_value=False)
    reply.code = 200
    reply.read.side_effect = IncompleteRead(b"partial", 20)
    opener = Mock()
    opener.open.return_value = reply
    monkeypatch.setattr(consumer, "build_opener", lambda *args: opener)
    result, _ = consumer.invoke_http(node, 2, "truncated")
    assert result.ret_code == -1 and result.ret_status == RetStatus.RetFail
    reply.__exit__.assert_called_once()


def test_caller_formats_ipv6_authority(monkeypatch, node):
    node.instance.host.value = "::1"
    opener = Mock()
    opener.open.return_value = response(200)
    monkeypatch.setattr(consumer, "build_opener", lambda *args: opener)
    consumer.invoke_http(node, 2, "ipv6")
    assert opener.open.call_args.args[0].full_url == "http://[::1]:8080/echo"


@pytest.mark.asyncio
async def test_async_caller_uses_async_discovery_and_report(monkeypatch, node):
    opener = Mock()
    opener.open.return_value = response(500)
    monkeypatch.setattr(consumer, "build_opener", lambda *args: opener)
    api = Mock()
    api.async_get_one_instance = AsyncMock(return_value=node)
    api.async_update_service_call_result = AsyncMock()
    outcome = await consumer.CircuitBreakerCaller(api, "default", "echo").async_call("async-id")
    assert outcome["ret_code"] == 500 and outcome["request_id"] == "async-id"
    api.async_get_one_instance.assert_awaited_once()
    api.async_update_service_call_result.assert_awaited_once()
    assert api.async_update_service_call_result.call_args.args[0].called_instance is node
    api.update_service_call_result.assert_not_called()
    api.get_one_instance.assert_not_called()
    api.sync_update_service_call_result.assert_not_called()


def test_caller_does_not_report_when_discovery_returns_none():
    api = Mock()
    api.get_one_instance.return_value = None
    with pytest.raises(RuntimeError, match="No provider instance"):
        consumer.CircuitBreakerCaller(api, "default", "echo").call()
    api.sync_update_service_call_result.assert_not_called()


def test_caller_snapshot_reads_full_response_instance_list(node):
    from types import SimpleNamespace
    api = Mock()
    api.get_all_instances.return_value = SimpleNamespace(instances=[node])
    states = consumer.CircuitBreakerCaller(api, "default", "echo").snapshot()
    assert [state["instance_id"] for state in states] == ["example-instance"]
    api.get_all_instances.assert_called_once()
    api.get_instances.assert_not_called()


@pytest.mark.parametrize("query, expected", [("openError=true", 500), ("openError=false", 200),
                                            ("status=404", 404), ("status=503", 503)])
def test_provider_switch_sets_http_status(query, expected):
    state = provider.ProviderState()
    assert state.switch(query) == expected and state.get_status() == expected


@pytest.mark.parametrize("query", ["", "openError=bad", "openError=", "status=199", "status=600", "status=abc",
                                   "status=500&status=200", "openError=true&status=500", "other=true"])
def test_provider_switch_rejects_invalid_values_without_changing_state(query):
    state = provider.ProviderState(503)
    with pytest.raises(ValueError):
        state.switch(query)
    assert state.get_status() == 503


@pytest.mark.parametrize("module", [consumer, provider])
def test_example_without_opt_in_never_creates_sdk_client(monkeypatch, capsys, module):
    monkeypatch.delenv("POLARIS_E2E", raising=False)
    constructor = Mock(side_effect=AssertionError("No SDK construction without opt-in"))
    monkeypatch.setattr(module, "create_consumer_by_config" if module is consumer else "create_provider_by_config", constructor)
    assert module.main([]) == 0
    assert '"skipped": true' in capsys.readouterr().out
    constructor.assert_not_called()


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf"])
def test_consumer_rejects_invalid_call_timeout(timeout):
    with pytest.raises(SystemExit) as error:
        consumer.main([f"--call-timeout={timeout}"])
    assert error.value.code == 2


@pytest.fixture
def listener(monkeypatch):
    server = Mock(server_address=("127.0.0.1", 12345))
    serving = Mock()
    for module in (consumer, provider):
        monkeypatch.setattr(module, "ThreadingHTTPServer", Mock(return_value=server))
    monkeypatch.setattr(provider.threading, "Thread", Mock(return_value=serving))
    return server, serving


def registration_request():
    return InstanceRegisterRequest("echo", "token", "default", "127.0.0.1", 0, ttl=1)


def test_provider_initialization_failure_closes_listener(monkeypatch, listener):
    server, serving = listener
    monkeypatch.setattr(provider, "create_provider_by_config", Mock(side_effect=RuntimeError("init failed")))
    with pytest.raises(RuntimeError, match="init failed"):
        with provider.running_provider(None, registration_request()):
            pytest.fail("Must not start after initialization failure")
    server.shutdown.assert_called_once()
    server.server_close.assert_called_once()
    serving.join.assert_called_once()


def test_provider_registration_failure_destroys_context(monkeypatch, listener):
    api = Mock()
    api.register_instance.side_effect = RuntimeError("register failed")
    monkeypatch.setattr(provider, "create_provider_by_config", Mock(return_value=api))
    with pytest.raises(RuntimeError, match="register failed"):
        with provider.running_provider(None, registration_request()):
            pytest.fail("Must not start after registration failure")
    api.deregister.assert_not_called()
    api.destroy.assert_called_once()
    listener[0].server_close.assert_called_once()


def test_provider_deregister_failure_still_destroys_context(monkeypatch, listener):
    api = Mock()
    api.register_instance.return_value = Mock(instance_id="registered-id")
    api.deregister.side_effect = RuntimeError("deregister failed")
    monkeypatch.setattr(provider, "create_provider_by_config", Mock(return_value=api))
    request = registration_request()
    with pytest.raises(RuntimeError, match="deregister failed"):
        with provider.running_provider(None, request):
            assert request.port == 12345
    removal = api.deregister.call_args.args[0]
    assert removal.instance_id == "registered-id" and removal.port == 12345
    api.destroy.assert_called_once()
    listener[0].server_close.assert_called_once()


def test_caller_body_failure_stops_and_closes_http_server(listener):
    with pytest.raises(RuntimeError, match="body failed"):
        with consumer.running_caller(Mock(), host="127.0.0.1", port=0):
            raise RuntimeError("body failed")
    server, serving = listener
    server.shutdown.assert_called_once()
    server.server_close.assert_called_once()
    serving.join.assert_called_once()
