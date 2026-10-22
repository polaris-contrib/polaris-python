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

"""Verify local instance circuits with real localhost HTTP and fake registry RPCs."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2])]
from examples._internal._runtime import verification_directory

import asyncio
import json
import threading
import time
from contextlib import ExitStack
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

from polaris import Configuration, ConsumerAPI, LogOptions, init_context_by_config
from polaris.pkg.model.server import InstanceRegisterRequest
from polaris.pkg.model.service import CBStatusEnum, GetInstancesRequest

EXAMPLE_DIR = Path(__file__).resolve().parent

from examples.circuitbreaker.consumer.main import CircuitBreakerCaller, running_caller
from examples.circuitbreaker.provider.main import running_provider


class RegistryStub:
    """Replace only the RPC boundary, keeping real SDK routing and circuit jobs."""
    def __init__(self):
        self.lock = threading.Lock()
        self.instances = {}
        self.registered = []
        self.heartbeats = []
        self.deregistered = []
        self.opened_streams = 0
        self.closed_streams = 0

    async def ReportClient(self, request, timeout=None, metadata=()):
        return response_pb2.Response(code={"value": 200000})

    async def RegisterInstance(self, request, timeout=None, metadata=()):
        assert request.host.value == "127.0.0.1"
        assert request.service_token.value == "example-token"
        assert request.health_check.heartbeat.ttl.value == 1
        instance = service_pb2.Instance()
        instance.CopyFrom(request)
        instance.id.value = f"instance-{request.port.value}"
        instance.healthy.value = True
        instance.weight.value = 100
        with self.lock:
            self.instances[instance.id.value] = instance
            self.registered.append(instance.id.value)
        return response_pb2.Response(code={"value": 200000}, instance=instance)

    async def Heartbeat(self, request, timeout=None, metadata=()):
        with self.lock:
            assert request.id.value in self.instances
            self.heartbeats.append(request.id.value)
        return response_pb2.Response(code={"value": 200000})

    async def DeregisterInstance(self, request, timeout=None, metadata=()):
        with self.lock:
            assert request.id.value in self.instances
            self.instances.pop(request.id.value)
            self.deregistered.append(request.id.value)
        return response_pb2.Response(code={"value": 200000})

    def Discover(self, requests, timeout=None, metadata=()):
        async def responses():
            with self.lock:
                self.opened_streams += 1
            try:
                async for request in requests:
                    response = response_pb2.DiscoverResponse(code={"value": 200000}, type=request.type,
                        service=service_pb2.Service(name=request.service.name, namespace=request.service.namespace,
                                                   revision={"value": "offline-revision"}))
                    if request.type == 1:
                        with self.lock:
                            for instance in self.instances.values():
                                if (instance.namespace == request.service.namespace and
                                        instance.service == request.service.name):
                                    response.instances.append(instance)
                    yield response
            finally:
                with self.lock:
                    self.closed_streams += 1
        return responses()


def configuration(role, backup_dir, **rules):
    config = Configuration.from_file(str(EXAMPLE_DIR / role / "polaris.yaml"), apply_env=False)
    connector = config.get_global().get_server_connector()
    connector.addresses = ["offline.invalid:8091"]
    connector.token = ""
    config.get_global().get_api().bind_ip = "127.0.0.1"
    config.get_consumer().get_local_cache().persist_dir = str(backup_dir)
    config.get_consumer().get_local_cache().service_refresh_interval = 20000
    for key, value in rules.items():
        setattr(config.get_consumer().get_circuit_breaker(), key, value)
    return config


def http_json(port, path, request_id="verify-request"):
    request = Request(f"http://127.0.0.1:{port}{path}", headers={"X-Request-ID": request_id})
    try:
        response = build_opener(ProxyHandler({})).open(request, timeout=2)
    except HTTPError as error:
        response = error
    with response:
        return response.code, json.loads(response.read())


def switch(port, status):
    code, body = http_json(port, f"/switch?status={status}")
    assert code == 200 and body == {"status": status}


def wait_for(predicate, description, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError(f"Timed out waiting for {description}")
        time.sleep(0.005)


def select_target(caller, instance_id):
    for _ in range(200):
        instance = caller.select()
        if instance.get_id() == instance_id:
            return instance
    raise AssertionError(f"Weighted random did not select {instance_id}")


def state(instance):
    return instance.get_circuit_breaker_status().get_status()


def verify(directory):
    stub = RegistryStub()
    clients = []

    async def fake_stub(connection, address):
        assert address == "offline.invalid:8091"
        return stub

    with patch("polaris.plugin.server_connector.grpc_connector.connection.GrpcConnection._stub", fake_stub):
        with ExitStack() as contexts, ExitStack() as services:
            def consumer(name, **rules):
                context = init_context_by_config(
                    configuration("consumer", directory.parent / "polaris" / "backup" / name, **rules),
                    log_options=LogOptions(level="info", log_dir=directory.parent / "polaris" / "log" / name))
                clients.append(context)
                contexts.callback(context.destroy)
                return ConsumerAPI(context)

            provider_ids = []
            ports = []
            for name, code in (("provider-a", 200), ("provider-b", 500)):
                request = InstanceRegisterRequest("CircuitBreakerCallee", "example-token", "default",
                                                  "127.0.0.1", 0, protocol="http", ttl=1)
                server, provider, response = services.enter_context(running_provider(
                    configuration("provider", directory.parent / "polaris" / "backup" / name), request,
                    status=code, listen_host="127.0.0.1",
                    log_options=LogOptions(level="info", log_dir=directory.parent / "polaris" / "log" / name)))
                clients.append(provider.context)
                provider_ids.append(response.instance_id)
                ports.append(server.server_address[1])

            api = consumer("caller", default_error_count=3, sleep_window=1000,
                           success_count_after_half_open=2, default_interval=1000)
            caller = CircuitBreakerCaller(api, "default", "CircuitBreakerCallee")
            nodes = api.get_all_instances(GetInstancesRequest(namespace="default", service="CircuitBreakerCallee"))
            by_id = {node.get_id(): node for node in nodes.instances}
            assert set(by_id) == set(provider_ids)
            first, second = (by_id[key] for key in provider_ids)
            frontend = services.enter_context(running_caller(caller, host="127.0.0.1", port=0))
            port = frontend.server_address[1]

            for code in (200, 404):
                switch(ports[0], code)
                for _ in range(4):
                    outcome = caller.call_instance(select_target(caller, first.get_id()), "classification")
                    assert outcome["ret_code"] == code and outcome["circuit_state"] == "closed"
                    assert json.loads(outcome["body"])["request_id"] == "classification"
            switch(ports[0], 200)
            print("PASS HTTP 200/404 classification and request-ID propagation")

            failures = 0
            for _ in range(200):
                code, outcome = http_json(port, "/echo")
                assert code == outcome["ret_code"]
                assert json.loads(outcome["body"])["request_id"] == "verify-request"
                if outcome["instance_id"] == second.get_id():
                    failures += 1
                    assert code == 500
                if state(second) == CBStatusEnum.Open:
                    break
            assert failures == 3 and state(second) == CBStatusEnum.Open
            for _ in range(8):
                code, outcome = http_json(port, "/echo")
                assert code == 200 and outcome["instance_id"] == first.get_id()
            code, snapshot = http_json(port, "/instances")
            assert code == 200
            assert {node["instance_id"]: node["circuit_state"] for node in snapshot} == {
                first.get_id(): "closed", second.get_id(): "open"}
            print("PASS configured consecutive failures open only the faulty instance; healthy routing")

            wait_for(lambda: state(second) == CBStatusEnum.HalfOpen, "first half-open timer")
            reserved = [select_target(caller, second.get_id()) for _ in range(2)]
            assert second.get_circuit_breaker_status().get_request_count_after_half_open() == 2
            for _ in range(8):
                assert caller.select().get_id() == first.get_id()
            outcome = caller.call_instance(reserved[0])
            assert outcome["ret_code"] == 500 and state(second) == CBStatusEnum.Open
            print("PASS configured two half-open permits; failed recovery immediately reopens")

            switch(ports[1], 200)
            wait_for(lambda: state(second) == CBStatusEnum.HalfOpen, "second half-open timer")
            for index in range(2):
                outcome = caller.call_instance(select_target(caller, second.get_id()))
                assert outcome["ret_code"] == 200
                assert state(second) == (CBStatusEnum.HalfOpen if index == 0 else CBStatusEnum.Closed)
            print("PASS real sleep timer and configured two-success recovery")

            rate_api = consumer("error-rate", default_error_count=100, default_interval=1000,
                                default_minimum_request=6, default_error_percent=50, sleep_window=1000)
            rate_caller = CircuitBreakerCaller(rate_api, "default", "CircuitBreakerCallee")
            switch(ports[1], 500)
            target = select_target(rate_caller, second.get_id())
            rate_caller.call_instance(target)
            time.sleep(0.3)
            # Fresh samples remain inside the sliding window at its first deadline.
            switch(ports[1], 200)
            for _ in range(3):
                assert rate_caller.call_instance(select_target(rate_caller, second.get_id()))["ret_code"] == 200
            switch(ports[1], 500)
            for _ in range(3):
                assert rate_caller.call_instance(select_target(rate_caller, second.get_id()))["ret_code"] == 500
            assert state(target) == CBStatusEnum.Closed
            wait_for(lambda: state(target) == CBStatusEnum.Open, "error-rate deadline")
            assert rate_caller.select().get_id() == first.get_id()
            print("PASS configured error-rate threshold/minimum requests with the real delayed check")

            switch(ports[0], 500)
            for node in (first, second):
                for _ in range(3):
                    caller.call_instance(node)
                assert state(node) == CBStatusEnum.Open
            code, outcome = http_json(port, "/echo")
            assert code == 500 and outcome["circuit_state"] == "open"
            print("PASS all-down fallback still calls an open instance")

            disabled_api = consumer("disabled", default_rule_enable=False, default_error_count=3)
            disabled = CircuitBreakerCaller(disabled_api, "default", "CircuitBreakerCallee")

            async def verify_async_disabled():
                for _ in range(12):
                    outcome = await disabled.async_call()
                    assert outcome["ret_code"] == 500 and outcome["circuit_state"] == "closed"

            asyncio.run(verify_async_disabled())
            assert disabled_api.context.engine._circuit_breaker_timers == {}
            print("PASS async discovery/HTTP/reporting and disabled default rule")

            async_api = consumer("async-caller", default_error_count=2, sleep_window=1000,
                                 success_count_after_half_open=1)
            async_caller = CircuitBreakerCaller(async_api, "default", "CircuitBreakerCallee")

            async def verify_async_recovery():
                result = await async_api.async_get_all_instances(GetInstancesRequest(
                    namespace="default", service="CircuitBreakerCallee"))
                node = next(node for node in result.instances if node.get_id() == second.get_id())
                for _ in range(200):
                    outcome = await async_caller.async_call()
                    if state(node) == CBStatusEnum.Open:
                        break
                assert outcome["ret_code"] == 500 and state(node) == CBStatusEnum.Open
                switch(ports[1], 200)
                async with asyncio.timeout(5):
                    while state(node) != CBStatusEnum.HalfOpen:
                        await asyncio.sleep(0.005)
                for _ in range(200):
                    outcome = await async_caller.async_call()
                    if outcome["instance_id"] == node.get_id():
                        assert outcome["ret_code"] == 200 and state(node) == CBStatusEnum.Closed
                        return
                raise AssertionError("Async caller did not select the recovering instance")

            asyncio.run(verify_async_recovery())
            print("PASS enabled async consecutive opening and one-success recovery")

            wait_for(lambda: set(stub.heartbeats) == set(provider_ids), "both automatic heartbeats")
            services.close()
            outcome = caller.call_instance(second)
            assert outcome["ret_code"] == -1
            assert stub.instances == {} and sorted(stub.deregistered) == sorted(provider_ids)
            print("PASS transport failure uses -1; both providers deregister on exit")

        for context in clients:
            engine = context.get_engine()
            assert context.is_destroy() and not engine.thread.is_alive()
            assert not engine.file_cache.write_thread.is_alive() and engine.file_cache.lock_file.closed
            assert engine._circuit_breaker_timers == engine.update_task_set == engine.registry.service_map == {}
            assert engine.svc_connector._streams == {}
            assert all(instance.handler.stream is None for instance in context.value_context.logger._categories.values())
        assert stub.opened_streams == stub.closed_streams
        print("PASS independent context/timer/stream/cache-writer cleanup")
        print(json.dumps({"passed_scenarios": 10, "external_registry": False, "destroyed_contexts": len(clients),
                          "registered": stub.registered, "deregistered": stub.deregistered}))


def main():
    with verification_directory(__file__) as directory:
        verify(Path(directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
