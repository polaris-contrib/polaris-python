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

"""Local default instance circuit rules and the real Engine/Consumer workflow."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

from polaris import Configuration, ConsumerAPI, LogOptions, SDKError, init_context_by_config
from polaris.pkg.flow import impl
from polaris.pkg.model.core import EventType, ServiceEventKey, ServiceKey
from polaris.pkg.model.service import (
    CBStatusEnum, CircuitBreakerStatus, DefaultInstanceLocalValue, GetInstancesRequest,
    GetOneInstanceRequest, Instance, RetStatus, ServiceCallResult, ServiceInstances,
)
from polaris.pkg.model.stat import Bucket, SlidingWindow
from polaris.plugin.circuit_breaker import composite
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection
from polaris.plugin.service_router.util import calc_available_instances


def make_instance(instance_id="instance-1", *, healthy=True):
    instance_value = service_pb2.Instance(
        id={"value": instance_id},
        host={"value": "127.0.0.1"},
        port={"value": 8080},
        healthy={"value": healthy},
        weight={"value": 100},
    )
    instance = Instance(instance_value, ServiceKey("Test", "svc"))
    instance.local_value = DefaultInstanceLocalValue()
    return instance


@pytest.fixture
def circuit(monkeypatch):
    cb = composite.CircuitBreaker()
    clock = [1000000]
    monkeypatch.setattr(cb, "now", lambda: clock[0])
    return cb, clock, make_instance()


@pytest.mark.parametrize("code, failed", [(-1, True), (500, True), (599, True), (0, False),
                                         (1, False), (200, False), (404, False), (499, False), (600, False)])
def test_default_return_code_classification(circuit, code, failed):
    cb, _, node = circuit
    for _ in range(9):
        assert not cb.realtime_circuit_break(node, code, 10)
    assert cb.realtime_circuit_break(node, code, 10) is failed
    metrics = node.local_value.circuit_breaker_metrics
    assert metrics.consecutive_errors == 0
    assert metrics.consecutive_suspended is failed
    assert metrics.consecutive_triggered is failed
    assert (metrics.error_rate_check_at is not None) is failed


def test_success_resets_consecutive_errors_across_buckets(circuit):
    cb, clock, node = circuit
    for _ in range(9):
        assert not cb.realtime_circuit_break(node, 500, 10)
    clock[0] += 6000
    assert not cb.realtime_circuit_break(node, 200, 10)
    for _ in range(9):
        assert not cb.realtime_circuit_break(node, 500, 10)
    assert cb.realtime_circuit_break(node, 500, 10)


def test_consecutive_errors_do_not_expire_with_metric_window(circuit):
    cb, clock, node = circuit
    for _ in range(9):
        assert not cb.realtime_circuit_break(node, 500, 10)
    clock[0] += 120000
    assert cb.realtime_circuit_break(node, 500, 10)


def test_continuous_bucket_property_is_not_total_failures():
    bucket = Bucket()
    bucket.total_failed = 9
    bucket.continuous_failed = 0
    assert bucket.continuous_failed == 0
    assert bucket.total_failed == 9


@pytest.mark.parametrize("success_count, fail_count, opens", [(5, 5, True), (6, 4, False), (4, 5, False)])
def test_error_rate_checks_at_window_deadline_and_threshold(circuit, success_count, fail_count, opens):
    cb, clock, node = circuit
    for code in [200] * success_count + [500] * fail_count:
        cb.realtime_circuit_break(node, code, 10)
    due = node.local_value.circuit_breaker_metrics.error_rate_check_at
    assert due == clock[0] + 60000
    assert not cb.close2Open(node, due - 1)
    assert cb.close2Open(node, due) is opens
    assert node.local_value.circuit_breaker_metrics.error_rate_check_at is None


def test_error_rate_schedules_once_until_check_finishes(circuit):
    cb, clock, node = circuit
    cb.realtime_circuit_break(node, 500, 10)
    first_due = cb.next_check_time(node)
    clock[0] += 20000
    cb.realtime_circuit_break(node, 500, 10)
    assert cb.next_check_time(node) == first_due
    clock[0] = first_due
    assert not cb.close2Open(node, clock[0])
    assert cb.next_check_time(node) is None
    cb.realtime_circuit_break(node, 500, 10)
    assert cb.next_check_time(node) == clock[0] + 60000


def test_error_rate_ignores_expired_buckets(circuit):
    cb, clock, node = circuit
    for _ in range(9):
        cb.realtime_circuit_break(node, 500, 10)
    clock[0] += 120000
    cb.realtime_circuit_break(node, 200, 10)
    assert not cb.close2Open(node, clock[0])


def test_sliding_window_starts_at_first_sample_and_excludes_end_boundary():
    window = SlidingWindow(10, 6000)
    window.add(1, lambda bucket, value: setattr(bucket, "total_failed", value), now=1000)
    window.add(1, lambda bucket, value: setattr(bucket, "success", value), now=6500)
    assert window.calc_interval_values(0, 6500) == (1, 1, 0)
    window.add(1, lambda bucket, value: setattr(bucket, "success", value), now=7000)
    assert window.calc_interval_values(7000, 13000) == (1, 0, 0)
    assert window.calc_interval_values(0, 7000) == (1, 1, 0)


def test_open_waits_full_sleep_window_without_health_probe(circuit):
    cb, clock, node = circuit
    node.local_value.cb_status = CircuitBreakerStatus(CBStatusEnum.Open, clock[0])
    node.instance.healthy.value = False
    assert not cb.open2halfopen(node, clock[0] + 29999)
    assert cb.open2halfopen(node, clock[0] + 30000)


def test_open_reports_still_dispatch_active_counters(circuit):
    cb, clock, node = circuit
    node.local_value.cb_status = CircuitBreakerStatus(CBStatusEnum.Open, clock[0])
    assert not cb.realtime_circuit_break(node, 500, 10)
    metrics = node.local_value.circuit_breaker_metrics
    assert metrics.consecutive_errors == 1
    assert metrics.error_rate_check_at == clock[0] + 60000


def test_error_rate_open_preserves_and_resumes_consecutive_counter(circuit):
    cb, clock, node = circuit
    for _ in range(9):
        cb.realtime_circuit_break(node, 500, 10)
    metrics = node.local_value.circuit_breaker_metrics
    metrics.window.add(1, lambda bucket, value: setattr(bucket, "success", value), now=clock[0])
    due = metrics.error_rate_check_at
    assert cb.close2Open(node, due)
    assert metrics.consecutive_errors == 9
    assert metrics.consecutive_suspended is False
    assert metrics.error_rate_suspended is True

    node.local_value.cb_status = CircuitBreakerStatus(CBStatusEnum.HalfOpen, clock[0],
                                                      allowed_requests_after_half_open=3)
    for _ in range(3):
        cb.realtime_circuit_break(node, 200, 10)
    node.local_value.cb_status = CircuitBreakerStatus(CBStatusEnum.Closed, clock[0])
    cb.on_state_change(node)
    assert node.local_value.circuit_breaker_metrics is metrics
    assert metrics.consecutive_errors == 9
    assert metrics.consecutive_suspended is False
    assert metrics.error_rate_suspended is False
    assert cb.realtime_circuit_break(node, 500, 10)


def test_half_open_ignores_historical_failures(circuit):
    cb, clock, node = circuit
    for _ in range(9):
        cb.realtime_circuit_break(node, 500, 10)
    node.local_value.cb_status = CircuitBreakerStatus(CBStatusEnum.HalfOpen, clock[0],
                                                     allowed_requests_after_half_open=3)
    assert not cb.halfopen2open(node, clock[0])
    assert not cb.halfopen2close(node, clock[0])
    for _ in range(2):
        assert not cb.realtime_circuit_break(node, 200, 10)
    assert cb.realtime_circuit_break(node, 200, 10)
    assert cb.halfopen2close(node, clock[0])
    assert node.local_value.cb_status.requests_after_half_open == 0


def test_half_open_one_failure_reopens_even_after_successes(circuit):
    cb, clock, node = circuit
    node.local_value.cb_status = CircuitBreakerStatus(CBStatusEnum.HalfOpen, clock[0])
    cb.realtime_circuit_break(node, 200, 10)
    assert cb.realtime_circuit_break(node, -1, 10)
    assert cb.halfopen2open(node, clock[0])
    assert not cb.halfopen2close(node, clock[0])


def test_half_open_allocates_exactly_three_permits_under_concurrency():
    status = CircuitBreakerStatus(CBStatusEnum.HalfOpen, allowed_requests_after_half_open=3)
    with ThreadPoolExecutor(max_workers=8) as pool:
        granted = list(pool.map(lambda _: status.try_allocate_request(), range(100)))
    assert sum(granted) == 3
    assert status.requests_after_half_open == 3
    assert not status.is_available()


def test_candidate_filtering_never_spends_half_open_permits():
    first, second = make_instance("first"), make_instance("second")
    for node in (first, second):
        node.local_value.cb_status = CircuitBreakerStatus(CBStatusEnum.HalfOpen,
                                                         allowed_requests_after_half_open=3)
    for _ in range(10):
        assert calc_available_instances(False, False, [first, second]) == [first, second]
    assert first.local_value.cb_status.requests_after_half_open == 0
    assert second.local_value.cb_status.requests_after_half_open == 0


class Stub:
    async def ReportClient(self, request, timeout=None, metadata=()):
        return response_pb2.Response(code={"value": 200000})

    def Discover(self, requests, timeout=None, metadata=()):
        async def responses():
            async for request in requests:
                response = response_pb2.DiscoverResponse(code={"value": 200000}, type=request.type,
                    service=service_pb2.Service(name=request.service.name, namespace=request.service.namespace,
                                               revision={"value": "revision-1"}))
                if request.type == 1:
                    for index in (1, 2):
                        response.instances.append(service_pb2.Instance(id={"value": f"instance-{index}"},
                            host={"value": "127.0.0.1"}, port={"value": 8080 + index},
                            healthy={"value": True}, weight={"value": 100}))
                yield response
        return responses()


@pytest.fixture
def clients(monkeypatch, tmp_path):
    created = []
    clock = [1000000]
    monkeypatch.setattr(composite.CircuitBreaker, "now", staticmethod(lambda: clock[0]))

    async def stub(connection, address):
        return Stub()

    monkeypatch.setattr(GrpcConnection, "_stub", stub)

    def create(*, enabled=True, configuration=None, **rule_options):
        cfg = configuration if configuration is not None else Configuration()
        cfg.set_default()
        cfg.get_global().get_api().bind_ip = "127.0.0.1"
        cfg.get_consumer().get_local_cache().persist_dir = str(tmp_path / str(len(created)) / "cache")
        cfg.get_consumer().get_circuit_breaker().enable = enabled
        for name, value in rule_options.items():
            setattr(cfg.get_consumer().get_circuit_breaker(), name, value)
        context = init_context_by_config(cfg, log_options=LogOptions(
            file_path=tmp_path / str(len(created)) / "client.log"))
        created.append(context)
        return ConsumerAPI(context)

    yield create, clock
    for context in created:
        context.destroy()
        assert not context.engine.thread.is_alive()
        assert context.engine._circuit_breaker_timers == {}


def result(instance, code=500, ret_status=RetStatus.RetFail):
    return ServiceCallResult(instance, ret_status, code, 10)


@pytest.mark.parametrize("source", ["yaml", "code"])
def test_context_applies_all_configured_local_rule_parameters(clients, source):
    create, _ = clients
    options = dict(sleep_window=1500, success_count_after_half_open=2, default_rule_enable=True,
                   default_error_count=4, default_error_percent=25, default_interval=2501,
                   default_minimum_request=8)
    if source == "yaml":
        cfg = Configuration.from_dict({"consumer": {"circuitBreaker": {
            "sleepWindow": "1500ms", "successCountAfterHalfOpen": 2, "defaultRuleEnable": True,
            "defaultErrorCount": 4, "defaultErrorPercent": 25, "defaultInterval": "2501ms",
            "defaultMinimumRequest": 8,
        }}}, apply_env=False)
    else:
        cfg = Configuration()
        cfg.set_default()
        for name, value in options.items():
            setattr(cfg.get_consumer().get_circuit_breaker(), name, value)
    consumer = create(configuration=cfg)
    cb = consumer.context.engine.circuit_breaker_chain["composite"]
    assert cb.enabled
    assert cb.plugin_config.continuous_error_threshold == 4
    assert cb.plugin_config.metric_stat_time_window == 2000
    assert cb.plugin_config.sleep_window == 1000
    assert cb.plugin_config.err_rate_threshold == 0.25
    assert cb.plugin_config.err_rate_request_threshold == 8
    assert cb.get_half_open_request_count() == cb.plugin_config.success_count_after_halfopen == 2
    node = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances[0]
    consumer.sync_update_service_call_result(result(node))
    assert node.local_value.window.bucket_count == 10
    assert node.local_value.window.bucket_interval == 200


def test_sync_consumer_uses_custom_consecutive_failure_threshold(clients):
    create, _ = clients
    consumer = create(default_error_count=3)
    node = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances[0]
    for _ in range(2):
        consumer.sync_update_service_call_result(result(node))
    consumer.sync_update_service_call_result(result(node, 200))
    for _ in range(2):
        consumer.sync_update_service_call_result(result(node))
        assert node.get_circuit_breaker_status().status == CBStatusEnum.Closed
    consumer.sync_update_service_call_result(result(node))
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Open


@pytest.mark.asyncio
async def test_configured_sleep_and_recovery_successes_control_half_open_permits(clients):
    create, clock = clients
    consumer = create(default_error_count=1, sleep_window=2000, success_count_after_half_open=2)
    engine = consumer.context.engine
    nodes = (await consumer.async_get_all_instances(GetInstancesRequest(service="svc", namespace="Test")))
    node = nodes.instances[0]
    await consumer.async_update_service_call_result(result(node))

    async def check():
        engine.do_circuit_break_for_service(ServiceKey("Test", "svc"), nodes)

    clock[0] += 1999
    await engine._run_async(check())
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Open
    clock[0] += 1
    await engine._run_async(check())
    status = node.get_circuit_breaker_status()
    assert status.status == CBStatusEnum.HalfOpen
    assert status.allowed_requests_after_half_open == 2
    engine.load_balancer.choose_instance = lambda instances: instances.instances[0]
    for _ in range(2):
        assert await consumer.async_get_one_instance(GetOneInstanceRequest(service="svc", namespace="Test")) is node
    assert await consumer.async_get_one_instance(GetOneInstanceRequest(service="svc", namespace="Test")) is nodes.instances[1]
    assert status.requests_after_half_open == 2
    await consumer.async_update_service_call_result(result(node, 200))
    assert node.get_circuit_breaker_status().status == CBStatusEnum.HalfOpen
    await consumer.async_update_service_call_result(result(node, 200))
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Closed


@pytest.mark.parametrize("threshold, minimum, successes, failures, opens", [
    (25, 4, 3, 0, True), (26, 4, 3, 0, False), (25, 5, 3, 0, False),
    (0, 4, 3, 0, True), (100, 4, 0, 3, True), (100, 4, 1, 2, False),
])
@pytest.mark.asyncio
async def test_configured_error_rate_window_threshold_and_minimum_sample_count(
        clients, threshold, minimum, successes, failures, opens):
    create, clock = clients
    consumer = create(default_error_count=100, default_interval=2500,
                      default_error_percent=threshold, default_minimum_request=minimum)
    engine = consumer.context.engine
    nodes = (await consumer.async_get_all_instances(GetInstancesRequest(service="svc", namespace="Test")))
    node = nodes.instances[0]
    await consumer.async_update_service_call_result(result(node))
    due = node.local_value.circuit_breaker_metrics.error_rate_check_at
    assert due == clock[0] + 2000
    clock[0] += 1000
    for code in [200] * successes + [500] * failures:
        await consumer.async_update_service_call_result(result(node, code))

    async def check():
        engine.do_circuit_break_for_service(ServiceKey("Test", "svc"), nodes)

    clock[0] = due - 1
    await engine._run_async(check())
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Closed
    clock[0] = due
    await engine._run_async(check())
    assert node.get_circuit_breaker_status().status == (CBStatusEnum.Open if opens else CBStatusEnum.Closed)


def test_sub_second_error_window_falls_back_to_sixty_seconds(clients):
    create, _ = clients
    consumer = create(default_interval=1)
    node = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances[0]
    consumer.sync_update_service_call_result(result(node))
    assert node.local_value.window.bucket_interval == 6000
    assert node.local_value.circuit_breaker_metrics.consecutive_errors == 1


@pytest.mark.asyncio
async def test_disabled_default_rule_has_no_statistics_or_jobs(clients):
    create, _ = clients
    consumer = create(default_rule_enable=False)
    engine = consumer.context.engine
    node = (await consumer.async_get_all_instances(GetInstancesRequest(service="svc", namespace="Test"))).instances[0]
    assert engine.circuit_breaker_chain == {}
    for _ in range(12):
        assert await consumer.async_update_service_call_result(result(node)) is None

    await asyncio.to_thread(consumer.sync_update_service_call_result, result(node))
    assert node.local_value.circuit_breaker_metrics is None
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Closed
    assert engine._circuit_breaker_timers == {}

    async def job_names():
        return {task.get_coro().__qualname__ for task in asyncio.all_tasks()}

    assert "Engine.timing_check_circuit_break_task" not in await engine._run_async(job_names())


def test_rule_parameters_are_snapshotted_for_each_context(clients):
    create, _ = clients
    cfg = Configuration()
    cfg.set_default()
    cfg.get_consumer().get_circuit_breaker().default_error_count = 2
    first = create(configuration=cfg)
    cfg.get_consumer().get_circuit_breaker().default_error_count = 4
    second = create(configuration=cfg)
    first.context.get_config().get_consumer().get_circuit_breaker().default_error_count = 99
    for consumer, threshold in ((first, 2), (second, 4)):
        node = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances[0]
        for _ in range(threshold - 1):
            consumer.sync_update_service_call_result(result(node))
            assert node.get_circuit_breaker_status().status == CBStatusEnum.Closed
        consumer.sync_update_service_call_result(result(node))
        assert node.get_circuit_breaker_status().status == CBStatusEnum.Open


def test_sync_consumer_consecutive_open_is_instance_local(clients):
    create, _ = clients
    consumer = create()
    nodes = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances
    for _ in range(9):
        consumer.sync_update_service_call_result(result(nodes[0]))
    assert nodes[0].get_circuit_breaker_status().status == CBStatusEnum.Closed
    consumer.sync_update_service_call_result(result(nodes[0]))
    assert nodes[0].get_circuit_breaker_status().status == CBStatusEnum.Open
    assert nodes[1].get_circuit_breaker_status().status == CBStatusEnum.Closed
    for _ in range(10):
        assert consumer.get_one_instance(GetOneInstanceRequest(service="svc", namespace="Test")).get_id() == "instance-2"


@pytest.mark.asyncio
async def test_async_consumer_immediate_half_open_failure_and_success_recovery(clients):
    create, clock = clients
    consumer = create()
    engine = consumer.context.engine
    nodes = (await consumer.async_get_all_instances(GetInstancesRequest(service="svc", namespace="Test")))
    node = nodes.instances[0]
    for _ in range(10):
        await consumer.async_update_service_call_result(result(node))
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Open

    async def check():
        engine.do_circuit_break_for_service(ServiceKey("Test", "svc"), nodes)

    clock[0] += 30000
    await engine._run_async(check())
    assert node.get_circuit_breaker_status().status == CBStatusEnum.HalfOpen
    assert node.get_circuit_breaker_status().allowed_requests_after_half_open == 3
    await consumer.async_update_service_call_result(result(node, 200, RetStatus.RetSuccess))
    await consumer.async_update_service_call_result(result(node, -1))
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Open
    assert node.get_circuit_breaker_status().ts == clock[0]
    clock[0] += 30000
    await engine._run_async(check())
    for _ in range(2):
        await consumer.async_update_service_call_result(result(node, 200, RetStatus.RetSuccess))
        assert node.get_circuit_breaker_status().status == CBStatusEnum.HalfOpen
    await consumer.async_update_service_call_result(result(node, 200, RetStatus.RetSuccess))
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Closed
    assert engine._circuit_breaker_timers == {}
    for _ in range(9):
        await consumer.async_update_service_call_result(result(node))
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Closed


def test_sdk_selection_spends_only_selected_instance_permit(clients):
    create, _ = clients
    consumer = create()
    engine = consumer.context.engine
    nodes = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances
    for node in nodes:
        node.local_value.cb_status = CircuitBreakerStatus(CBStatusEnum.HalfOpen,
                                                         allowed_requests_after_half_open=3)
    engine.load_balancer.choose_instance = lambda instances: instances.instances[0]
    for _ in range(3):
        assert consumer.get_one_instance(GetOneInstanceRequest(service="svc", namespace="Test")) is nodes[0]
    assert nodes[0].get_circuit_breaker_status().requests_after_half_open == 3
    assert nodes[1].get_circuit_breaker_status().requests_after_half_open == 0
    assert consumer.get_one_instance(GetOneInstanceRequest(service="svc", namespace="Test")) is nodes[1]


def test_concurrent_sdk_selection_allocates_three_half_open_permits(clients):
    create, _ = clients
    consumer = create()
    engine = consumer.context.engine
    nodes = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances
    nodes[0].local_value.cb_status = CircuitBreakerStatus(CBStatusEnum.HalfOpen,
                                                        allowed_requests_after_half_open=3)
    engine.load_balancer.choose_instance = lambda instances: instances.instances[0]

    def select(_):
        return consumer.get_one_instance(GetOneInstanceRequest(service="svc", namespace="Test"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        selected = list(pool.map(select, range(24)))
    assert selected.count(nodes[0]) == 3
    assert selected.count(nodes[1]) == 21
    assert nodes[0].local_value.cb_status.requests_after_half_open == 3


def test_sdk_all_down_fallback_keeps_returning_exhausted_half_open_instance(clients):
    create, _ = clients
    consumer = create()
    nodes = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances
    for node in nodes:
        node.local_value.cb_status = CircuitBreakerStatus(CBStatusEnum.HalfOpen,
            requests_after_half_open=3, allowed_requests_after_half_open=3)
    assert consumer.get_one_instance(GetOneInstanceRequest(service="svc", namespace="Test")) in nodes
    assert [node.local_value.cb_status.requests_after_half_open for node in nodes] == [3, 3]


def test_sdk_all_down_fallback_keeps_returning_open_instance(clients):
    create, _ = clients
    consumer = create()
    nodes = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances
    for node in nodes:
        node.local_value.cb_status = CircuitBreakerStatus(CBStatusEnum.Open, 1000000)
    assert consumer.get_one_instance(GetOneInstanceRequest(service="svc", namespace="Test")) in nodes


def test_disabled_breaker_accepts_reports_without_statistics_or_timers(clients):
    create, _ = clients
    consumer = create(enabled=False)
    nodes = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances
    for _ in range(11):
        assert consumer.sync_update_service_call_result(result(nodes[0])) is None
    assert nodes[0].local_value.circuit_breaker_metrics is None
    assert nodes[0].get_circuit_breaker_status().status == CBStatusEnum.Closed
    assert consumer.context.engine._circuit_breaker_timers == {}

    async def job_names():
        return {task.get_coro().__qualname__ for task in asyncio.all_tasks()}

    assert "Engine.timing_check_circuit_break_task" not in consumer.context.engine._run_sync(job_names())


@pytest.mark.asyncio
async def test_async_reports_to_disabled_breaker_are_noop(clients):
    create, _ = clients
    consumer = create(enabled=False)
    node = (await consumer.async_get_all_instances(GetInstancesRequest(service="svc", namespace="Test"))).instances[0]
    assert await consumer.async_update_service_call_result(result(node)) is None
    assert node.local_value.circuit_breaker_metrics is None


def test_reports_cannot_modify_another_contexts_instance(clients):
    create, _ = clients
    first, second = create(), create()
    first_node = first.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances[0]
    second_node = second.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances[0]
    for _ in range(10):
        second.sync_update_service_call_result(result(first_node))
    assert first_node.get_circuit_breaker_status().status == CBStatusEnum.Closed
    assert second_node.get_circuit_breaker_status().status == CBStatusEnum.Closed
    for _ in range(10):
        first.sync_update_service_call_result(result(first_node))
    assert first_node.get_circuit_breaker_status().status == CBStatusEnum.Open
    assert second_node.get_circuit_breaker_status().status == CBStatusEnum.Closed
    first.destroy()
    second.sync_update_service_call_result(result(second_node, 200))


@pytest.mark.asyncio
async def test_result_classification_uses_code_not_ret_status(clients):
    create, _ = clients
    consumer = create()
    node = (await consumer.async_get_all_instances(GetInstancesRequest(service="svc", namespace="Test"))).instances[0]
    for _ in range(10):
        await consumer.async_update_service_call_result(result(node, 404, RetStatus.RetFail))
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Closed
    for _ in range(10):
        await consumer.async_update_service_call_result(result(node, 500, RetStatus.RetSuccess))
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Open


def test_report_api_rejects_destroyed_context(clients):
    create, _ = clients
    consumer = create()
    node = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances[0]
    consumer.destroy()
    with pytest.raises(SDKError):
        consumer.sync_update_service_call_result(result(node))


@pytest.mark.asyncio
async def test_async_report_api_rejects_destroyed_context(clients):
    create, _ = clients
    consumer = create()
    node = (await consumer.async_get_all_instances(GetInstancesRequest(service="svc", namespace="Test"))).instances[0]
    consumer.destroy()
    with pytest.raises(SDKError):
        await consumer.async_update_service_call_result(result(node))


class Handle:
    def __init__(self, delay, callback):
        self.delay, self.callback, self._cancelled = delay, callback, False

    def cancel(self):
        self._cancelled = True

    def cancelled(self):
        return self._cancelled


class TimerLoop:
    def __init__(self):
        self.handles = []

    def call_later(self, delay, callback):
        handle = Handle(delay, callback)
        self.handles.append(handle)
        return handle


class Registry:
    def __init__(self, node):
        self.instances = ServiceInstances(service=service_pb2.Service(name={"value": "svc"},
            namespace={"value": "Test"}), instances=[node], instances_map={node.get_id(): node}, initialized=True)

    def get_instances(self, request):
        return self.instances

    def update_instances(self, request):
        for properties in request.properties:
            self.instances.instances_map[properties.ID].local_value.cb_status = properties.properties["CircuitBreakerStatus"]


def test_owner_loop_timer_replaces_error_check_with_sleep_and_fires(circuit):
    cb, clock, node = circuit
    engine = impl.Engine(registry=Registry(node), circuit_breaker_chain={"composite": cb})
    engine.loop = TimerLoop()
    cb.realtime_circuit_break(node, 500, 10)
    engine._schedule_circuit_break_check(node, "composite", cb)
    first = engine.loop.handles[0]
    assert first.delay == 60
    cb.realtime_circuit_break(node, 500, 10)
    engine._schedule_circuit_break_check(node, "composite", cb)
    assert len(engine.loop.handles) == 1
    for _ in range(8):
        cb.realtime_circuit_break(node, 500, 10)
    engine.do_circuit_break_for_service(ServiceKey("Test", "svc"), engine.registry.instances)
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Open
    assert first.cancelled()
    sleeper = engine.loop.handles[1]
    assert sleeper.delay == 30
    clock[0] += 30000
    sleeper.callback()
    assert node.get_circuit_breaker_status().status == CBStatusEnum.HalfOpen
    assert node.get_circuit_breaker_status().allowed_requests_after_half_open == 3
    assert engine._circuit_breaker_timers == {}


def test_error_rate_timer_applies_fifty_percent_boundary(circuit):
    cb, clock, node = circuit
    engine = impl.Engine(registry=Registry(node), circuit_breaker_chain={"composite": cb})
    engine.loop = TimerLoop()
    for code in [200] * 5 + [500] * 5:
        cb.realtime_circuit_break(node, code, 10)
    engine._schedule_circuit_break_check(node, "composite", cb)
    assert engine.loop.handles[0].delay == 60
    clock[0] += 60000
    engine.loop.handles[0].callback()
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Open
    assert engine.loop.handles[1].delay == 30


def test_timer_and_report_ignore_removed_instance_generation(circuit):
    cb, clock, node = circuit
    registry = Registry(node)
    engine = impl.Engine(registry=registry, circuit_breaker_chain={"composite": cb})
    engine.loop = TimerLoop()
    cb.realtime_circuit_break(node, 500, 10)
    engine._schedule_circuit_break_check(node, "composite", cb)
    new_node = make_instance()
    registry.instances.instances_map[node.get_id()] = new_node
    registry.instances.instances = [new_node]
    clock[0] += 60000
    engine.loop.handles[0].callback()
    asyncio.run(engine._update_service_call_result(result(node)))
    assert new_node.local_value.circuit_breaker_metrics is None
    assert engine._circuit_breaker_timers == {}


def test_instance_removal_cancels_timer_but_same_id_refresh_preserves_it(circuit):
    cb, _, node = circuit
    registry = Registry(node)
    engine = impl.Engine(registry=registry, circuit_breaker_chain={"composite": cb})
    engine.loop = TimerLoop()
    cb.realtime_circuit_break(node, 500, 10)
    engine._schedule_circuit_break_check(node, "composite", cb)
    handle = engine.loop.handles[0]
    refreshed = make_instance()
    refreshed.local_value = node.local_value
    registry.instances.instances_map[node.get_id()] = refreshed
    key = ServiceEventKey("Test", "svc", EventType.Instance)
    engine._prune_circuit_breaker_timers(key, registry.instances)
    assert not handle.cancelled()
    registry.instances.instances_map.clear()
    engine._prune_circuit_breaker_timers(key, registry.instances)
    assert handle.cancelled()
    assert engine._circuit_breaker_timers == {}


@pytest.mark.asyncio
async def test_eviction_cancels_timer_for_instance_resource(circuit):
    cb, _, node = circuit
    engine = impl.Engine(registry=Registry(node), circuit_breaker_chain={"composite": cb})
    engine.loop = TimerLoop()

    class Connector:
        async def stop_discover(self, request):
            pass

    class Files:
        async def delete(self, request):
            pass

    engine.svc_connector, engine.file_cache = Connector(), Files()
    cb.realtime_circuit_break(node, 500, 10)
    engine._schedule_circuit_break_check(node, "composite", cb)
    handle = engine.loop.handles[0]
    await engine.stop_service_update(ServiceEventKey("Test", "svc", EventType.Instance), object())
    assert handle.cancelled()
    assert engine._circuit_breaker_timers == {}


@pytest.mark.asyncio
async def test_periodic_circuit_checks_only_instance_resources(circuit, monkeypatch):
    cb, _, node = circuit
    registry = Registry(node)
    cfg = Configuration()
    cfg.set_default()
    cfg.get_consumer().get_circuit_breaker().check_period = 10000
    engine = impl.Engine(config=cfg, registry=registry, circuit_breaker_chain={"composite": cb})
    services = {ServiceEventKey("Test", "svc", kind): object()
                for kind in (EventType.Instance, EventType.Routing)}
    registry.get_services = lambda: services
    checked = []
    engine.do_circuit_break_for_service = lambda key, instances: checked.append(key)

    async def finish_after_scan(delay):
        assert delay == 10
        raise asyncio.CancelledError

    monkeypatch.setattr(impl.asyncio, "sleep", finish_after_scan)
    with pytest.raises(asyncio.CancelledError):
        await engine.timing_check_circuit_break_task()
    assert checked == [ServiceEventKey("Test", "svc", EventType.Instance)]


@pytest.mark.asyncio
async def test_real_owner_loop_fires_error_rate_and_sleep_callbacks(clients, monkeypatch):
    create, _ = clients
    monkeypatch.setattr(composite.CircuitBreaker, "now", staticmethod(
        lambda: int(asyncio.get_running_loop().time() * 1000)))
    consumer = create(default_interval=1000, sleep_window=1000)
    engine = consumer.context.engine
    # Keep fresh samples in the window when the actual delayed callback runs.
    nodes = (await consumer.async_get_all_instances(GetInstancesRequest(service="svc", namespace="Test")))
    node = nodes.instances[0]
    await consumer.async_update_service_call_result(result(node, 500))
    await asyncio.sleep(0.3)

    async def report_fresh_samples():
        for code in [200] * 5 + [500] * 5:
            await engine._update_service_call_result(result(node, code))

    await engine._run_async(report_fresh_samples())
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Closed

    async def wait_for(target):
        async with asyncio.timeout(5):
            while node.get_circuit_breaker_status().status != target:
                await asyncio.sleep(0.005)

    await wait_for(CBStatusEnum.Open)
    await wait_for(CBStatusEnum.HalfOpen)
    for _ in range(3):
        await consumer.async_update_service_call_result(result(node, 200))
    assert node.get_circuit_breaker_status().status == CBStatusEnum.Closed
    assert engine._circuit_breaker_timers == {}


@pytest.mark.asyncio
async def test_refresh_keeps_local_counters_and_initializes_new_instances(clients):
    create, _ = clients
    consumer = create()
    engine = consumer.context.engine
    nodes = (await consumer.async_get_all_instances(GetInstancesRequest(service="svc", namespace="Test")))
    old = nodes.instances[0]
    await consumer.async_update_service_call_result(result(old))
    key = ServiceEventKey("Test", "svc", EventType.Instance)
    task = engine.update_task_set[key]
    cb = engine.circuit_breaker_chain["composite"]
    metrics = old.local_value.circuit_breaker_metrics

    async def discover(request, use_discover_cache=True):
        response = response_pb2.DiscoverResponse(code={"value": 200000}, type=1,
            service=service_pb2.Service(name={"value": "svc"}, namespace={"value": "Test"},
                                       revision={"value": "revision-2"}))
        for instance_id in ("instance-1", "instance-3"):
            response.instances.append(service_pb2.Instance(id={"value": instance_id},
                host={"value": "127.0.0.1"}, port={"value": 8080}, healthy={"value": True}, weight={"value": 100}))
        return response

    engine.svc_connector.discover = discover

    async def refresh():
        await engine.process_update_task(task)
        assert task.cache_obj.value.instances[0].local_value is old.local_value
        assert old.local_value.circuit_breaker_metrics is metrics
        assert metrics.consecutive_errors == 1
        new_node = task.cache_obj.value.instances[1]
        assert new_node.local_value.circuit_breaker_metrics is None
        cb.realtime_circuit_break(new_node, 500, 1)
        assert new_node.local_value.window.bucket_count == 10
        assert new_node.local_value.window.bucket_interval == 6000
        assert new_node.local_value.circuit_breaker_metrics is not metrics

    await engine._run_async(refresh())


def test_destroy_cancels_and_forgets_existing_timer_handles(clients):
    create, _ = clients
    consumer = create()
    engine = consumer.context.engine
    node = consumer.get_all_instances(GetInstancesRequest(service="svc", namespace="Test")).instances[0]
    consumer.sync_update_service_call_result(result(node))
    handles = [entry[0] for entry in engine._circuit_breaker_timers.values()]
    assert len(handles) == 1
    consumer.destroy()
    assert all(handle.cancelled() for handle in handles)
    assert engine._circuit_breaker_timers == {}
