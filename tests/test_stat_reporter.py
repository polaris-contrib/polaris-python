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

"""Exercise period gauges, actual pull/push HTTP and context lifecycle."""

import asyncio
from types import SimpleNamespace

import pytest
from aiohttp import ClientSession, web
from prometheus_client.parser import text_string_to_metric_families

from polaris import Configuration, ConsumerAPI, ProviderAPI, init_context_by_config
from polaris.pkg.model.context import new_value_context
from polaris.pkg.model.error import SDKError
from polaris.pkg.model.service import RetStatus, ServiceCallResult, ServiceInfo
from polaris.pkg.model.service import Instance
from polaris.pkg.model.server import InstanceRegisterRequest
from polaris.plugin.stat_reporter.prometheus import PrometheusReporter, METRICS, NULL
from polaris.plugin_manager import InitContext
from tests.test_ai import runtime


def reporter(**options):
    config = Configuration.from_dict({"global": {"admin": {"host": "127.0.0.1", "port": 0},
        "api": {"bindIP": "192.0.2.1"}, "statReporter": {"plugin": {"prometheus": options}}}}, apply_env=False)
    config.set_default()
    config.verify()
    return PrometheusReporter(InitContext(config, new_value_context()))


def call(delay=12, **kwargs):
    return ServiceCallResult(namespace="ns", service="svc", host="127.0.0.1", port=8080,
                             ret_status=RetStatus.RetSuccess, ret_code=200, delay=delay, **kwargs)


def samples(data):
    return {name: [sample for family in text_string_to_metric_families(data.decode())
                   for sample in family.samples if sample.name == name] for name in METRICS}


def test_java_period_gauges_labels_regex_and_idle_cleanup():
    stats = reporter(pathRegexList=["/users/.*"])
    for delay in (12, 7, 20):
        stats.report(call(delay, method="/users/123", caller_service=ServiceInfo("caller", "client"),
                          labels="env=test"))
    stats.aggregate()
    values = samples(stats.render())
    assert [values[name][0].value for name in METRICS] == [3, 3, 39, 20, 7]
    labels = values["upstream_rq_total"][0].labels
    assert labels["callee_method"] == "/users/.*"
    assert labels["caller_namespace"] == "client"
    assert labels["caller_service"] == "caller"
    assert labels["caller_ip"] == "192.0.2.1"
    assert labels["caller_labels"] == "env=test"
    assert labels["metric_name"] == NULL
    stats.aggregate()
    assert samples(stats.render())["upstream_rq_total"][0].value == 0
    stats.aggregate()
    stats.aggregate()
    assert samples(stats.render())["upstream_rq_total"] == []


@pytest.mark.parametrize("status", list(RetStatus.descriptions))
def test_result_status_and_missing_delay(status):
    stats = reporter()
    result = call(None)
    result.ret_status = status
    result.ret_code = None
    stats.report(result)
    stats.aggregate()
    values = samples(stats.render())
    assert values["upstream_rq_success"][0].value == int(status == RetStatus.RetSuccess)
    assert values["upstream_rq_timeout"][0].value == 0
    assert values["upstream_rq_total"][0].labels["callee_result_code"] == NULL


@pytest.mark.asyncio
async def test_real_pull_listener_and_close_release_port():
    stats = reporter(path="/custom")
    await stats.start(None)
    stats.report(call(method="echo"))
    stats.aggregate()
    port = stats.port
    assert stats.meta_info() == {"target": "prometheus", "port": port, "path": "/custom", "protocol": "http"}
    try:
        async with ClientSession() as client:
            async with client.get(f"http://127.0.0.1:{port}/custom") as response:
                assert response.status == 200
                assert b'callee_method="echo"' in await response.read()
            async with client.get(f"http://127.0.0.1:{port}/unknown") as response:
                assert response.status == 404
    finally:
        await stats.close()
    assert stats.runner is None and stats.task is None
    assert stats.meta_info() is None
    server = await asyncio.start_server(lambda reader, writer: writer.close(), "127.0.0.1", port)
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_push_concurrent_call_is_retained_on_success_and_failure(fail):
    received, entered, release = [], asyncio.Event(), asyncio.Event()
    status = 503 if fail else 200

    async def accept(request):
        received.append((request.path, request.headers, await request.read()))
        entered.set()
        await release.wait()
        return web.Response(status=status)

    app = web.Application()
    app.router.add_post("/{path:.*}", accept)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    stats = reporter(type="push", address=[f"127.0.0.1:{port}"], openGzip=True)
    await stats.start(None)
    assert stats.meta_info() is None
    try:
        stats.report(call())
        pending = asyncio.create_task(stats.push())
        await asyncio.wait_for(entered.wait(), 3)
        stats.report(call(8))
        release.set()
        if fail:
            with pytest.raises(SDKError, match="HTTP 503"):
                await pending
            assert stats.period == 0
        else:
            await pending
            assert stats.period == 1
        assert received[0][0].endswith(f"/metrics/job/polaris-client/instance/{stats.client_id}")
        assert received[0][1]["Content-Encoding"] == "gzip"
        assert samples(received[0][2])["upstream_rq_total"][0].value == 1
        stats.aggregate(advance=False)
        assert samples(stats.render())["upstream_rq_total"][0].value == (2 if fail else 1)
        status = 200
        await stats.push()
        assert stats.period == (1 if fail else 2)
    finally:
        await stats.close()
        await runner.cleanup()


@pytest.mark.parametrize("options", [
    {"type": "other"}, {"pushInterval": "1ms"}, {"address": ["bad"]},
    {"pathRegexList": ["["]}, {"openGzip": "yes"}, {"address": ["http://user:pass@host:80"]},
])
def test_invalid_monitor_configuration(options):
    with pytest.raises(SDKError):
        config = Configuration.from_dict({"global": {"statReporter": {"plugin": {"prometheus": options}}}},
                                         apply_env=False)
        config.set_default()
        config.verify()


def test_code_configuration_getter_keeps_assignments():
    config = Configuration()
    config.set_default()
    options = config.get_global().get_stat_reporter().get_prometheus()
    options.path = "/custom"
    assert config.get_global().get_stat_reporter().get_prometheus().path == "/custom"


def test_internal_register_and_application_reports_share_context_metrics(runtime):
    _, context, _ = runtime
    provider, consumer = ProviderAPI(context), ConsumerAPI(context)
    provider.register(InstanceRegisterRequest(namespace="ns", service="svc", service_token="token", host="127.0.0.1", port=8080))
    consumer.update_service_call_result(call(method="echo", instance_type="a2a"))
    stats = context.engine.stat_reporter
    stats.aggregate()
    methods = {sample.labels["callee_method"] for sample in samples(stats.render())["upstream_rq_total"]}
    assert methods == {"register", "echo"}


def test_a2a_and_mcp_metric_conventions_use_instance_type_and_method():
    stats = reporter()
    stats.report(call(method="message/send", instance_type="a2a"))
    stats.report(call(method="search_tool", instance_type="mcp", labels="agent=demo"))
    stats.aggregate()
    values = samples(stats.render())["upstream_rq_total"]
    labels = {(item.labels["callee_instance_type"], item.labels["callee_method"],
               item.labels["caller_labels"]) for item in values}
    assert labels == {("a2a", "message/send", "__NULL__"), ("mcp", "search_tool", "agent=demo")}


def test_sdk_client_report_contains_pull_endpoint(runtime):
    import time
    stub, context, _ = runtime
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not any(item[0] == "ReportClient" for item in stub.calls):
        time.sleep(0.01)
    request = next(item[1] for item in stub.calls if item[0] == "ReportClient")
    assert len(request.stat) == 1
    assert request.stat[0].target.value == "prometheus"
    assert request.stat[0].port.value == context.engine.stat_reporter.port
    assert request.stat[0].path.value == "/metric"
    assert request.stat[0].protocol.value == "http"


@pytest.mark.asyncio
async def test_async_report_and_destroyed_context(runtime):
    _, context, _ = runtime
    api = ConsumerAPI(context)
    await api.async_update_service_call_result(call())
    context.destroy()
    with pytest.raises(SDKError):
        await api.async_update_service_call_result(call())


def test_fixed_monitor_port_conflict_releases_failed_context(runtime, tmp_path):
    _, context, _ = runtime
    config = context.config
    config.get_global().get_admin().port = context.engine.stat_reporter.port
    with pytest.raises(SDKError, match="Cannot bind metrics"):
        init_context_by_config(config)
    assert not context.is_destroy()
    context.engine.stat_reporter.report(call())


@pytest.mark.asyncio
async def test_push_monitor_cluster_discovery_override_host_and_cancel_merge():
    from tests.test_ai import instance
    requests, entered = [], asyncio.Event()

    async def accept(request):
        requests.append(await request.read())
        entered.set()
        await asyncio.sleep(30)
        return web.Response()

    app = web.Application()
    app.router.add_post("/{path:.*}", accept)
    runner = web.AppRunner(app, shutdown_timeout=0.01)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    node = Instance(instance("gateway", port), ServiceInfo("polaris.pushgateway", "Polaris"))
    node.instance.host.value = "unreachable.example"
    queries = []

    async def discover(request):
        queries.append((request.namespace, request.service))
        return node

    stats = reporter(type="push", overrideHost="127.0.0.1")
    await stats.start(SimpleNamespace(_async_get_one_instance=discover))
    try:
        stats.report(call())
        pending = asyncio.create_task(stats.push())
        await asyncio.wait_for(entered.wait(), 3)
        stats.report(call(8))
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert queries == [("Polaris", "polaris.monitor")]
        assert stats.period == 0 and not stats.pushing
        stats.aggregate(advance=False)
        assert samples(stats.render())["upstream_rq_total"][0].value == 2
    finally:
        await stats.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_monitor_context_isolation_and_independent_destroy(runtime):
    _, first, create = runtime
    second = create()
    first.engine.stat_reporter.report(call(method="first"))
    second.engine.stat_reporter.report(call(method="second"))
    first.engine.stat_reporter.aggregate()
    second.engine.stat_reporter.aggregate()
    assert first.engine.stat_reporter.port != second.engine.stat_reporter.port
    first.destroy()
    async with ClientSession() as client:
        async with client.get(f"http://127.0.0.1:{second.engine.stat_reporter.port}/metric") as response:
            payload = await response.read()
            assert b'callee_method="second"' in payload
            assert b'callee_method="first"' not in payload
    assert not second.is_destroy()
