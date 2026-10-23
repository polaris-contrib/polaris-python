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

"""Verify implemented instance-cache and local circuit-breaker events."""

import asyncio
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._internal._ai_stub import AIStub
from examples._internal._runtime import demo_backup_directory, demo_log_options, verification_directory
from polaris import Configuration, ConsumerAPI, SDKEventName, SDKEventType, init_context_by_config
from polaris.pkg.model.core import EventType, ServiceEventKey, ServiceKey
from polaris.pkg.model.server import InstanceDiscoverRequest
from polaris.pkg.model.service import GetInstancesRequest, RetStatus, ServiceCallResult
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection


def node(node_id="event-node", port=18080):
    return service_pb2.Instance(
        id={"value": node_id}, host={"value": "127.0.0.1"}, port={"value": port},
        service={"value": "svc"}, namespace={"value": "ns"},
        healthy={"value": True}, weight={"value": 100},
    )


def missing(requests, timeout=None, metadata=()):
    async def responses():
        async for request in requests:
            yield response_pb2.DiscoverResponse(code={"value": 400301}, type=request.type,
                                                service=request.service)
    return responses()


async def verify():
    stub = AIStub()
    stub.instances = [node()]
    pushed = []

    async def accept_event(request):
        pushed.append(json.loads(await request.text()))
        return web.Response()

    app = web.Application()
    app.router.add_post("/{path:.*}", accept_event)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    event_port = site._server.sockets[0].getsockname()[1]

    async def fake_stub(connection, address):
        return stub

    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = ["offline:8091"]
    config.get_global().get_api().bind_ip = "127.0.0.1"
    config.get_global().get_admin().port = 0
    config.get_consumer().get_local_cache().persist_dir = str(demo_backup_directory(__file__))
    config.get_consumer().get_local_cache().service_refresh_interval = 60000
    circuit = config.get_consumer().get_circuit_breaker()
    circuit.default_error_count = 1
    circuit.sleep_window = 1000
    circuit.success_count_after_half_open = 1
    event_reporter = config.get_global().get_event_reporter()
    event_reporter.enable = True
    event_reporter.chain = ["pushgateway"]
    pushgateway = event_reporter.get_pushgateway()
    pushgateway.address = [f"127.0.0.1:{event_port}"]
    pushgateway.push_interval = 10
    pushgateway.retry_interval = 1

    with patch.object(GrpcConnection, "_stub", fake_stub):
        context = init_context_by_config(config, log_options=demo_log_options(__file__))
        context.engine.svc_connector.connection.settings = replace(
            context.engine.svc_connector.connection.settings, refresh_interval_seconds=0.01)
        events = []
        try:
            context.get_event_center().register_listener(lambda event: events.append(event.event_name))
            consumer = ConsumerAPI(context)
            request = GetInstancesRequest(namespace="ns", service="svc")
            snapshot = await consumer.async_get_all_instances(request)
            assert events == [SDKEventName.ON_SERVICE_ADDED]

            task = context.engine.update_task_set[ServiceEventKey("ns", "svc", EventType.Instance)]
            task.last_update_time = 0
            await context.engine._run_async(context.engine.process_update_task(task))
            assert events[-1] == SDKEventName.ON_SERVICE_UPDATED

            selected = snapshot.instances[0]
            await consumer.async_update_service_call_result(ServiceCallResult(
                selected, RetStatus.RetFail, 500, 1))
            context.engine.do_circuit_break_for_service(ServiceKey("ns", "svc"), snapshot)
            assert events[-1] == SDKEventName.CIRCUIT_BREAKER_OPEN

            time.sleep(1.1)
            context.engine.do_circuit_break_for_service(ServiceKey("ns", "svc"), snapshot)
            assert events[-1] == SDKEventName.CIRCUIT_BREAKER_HALF_OPEN
            await consumer.async_update_service_call_result(ServiceCallResult(
                selected, RetStatus.RetSuccess, 200, 1))
            context.engine.do_circuit_break_for_service(ServiceKey("ns", "svc"), snapshot)
            assert events[-1] == SDKEventName.CIRCUIT_BREAKER_CLOSE

            await context.engine._run_async(context.engine.svc_connector.stop_discover(
                InstanceDiscoverRequest(1, "svc", "ns")))
            stub.Discover = missing
            task.last_update_time = 0
            await context.engine._run_async(context.engine.process_update_task(task))
            assert events[-1] == SDKEventName.ON_SERVICE_DELETED

            expected = [SDKEventName.ON_SERVICE_ADDED, SDKEventName.ON_SERVICE_UPDATED,
                        SDKEventName.CIRCUIT_BREAKER_OPEN, SDKEventName.CIRCUIT_BREAKER_HALF_OPEN,
                        SDKEventName.CIRCUIT_BREAKER_CLOSE, SDKEventName.ON_SERVICE_DELETED]
            assert events == expected
            await asyncio.sleep(0.05)
            pushed_names = [item["event_name"] for batch in pushed for item in batch["batch"]]
            assert pushed_names == expected
            result = {"events": "passed", "sequence": events}
            print(json.dumps(result), flush=True)
            return result
        finally:
            context.destroy()
            await runner.cleanup()


def main():
    with verification_directory(__file__):
        asyncio.run(verify())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
