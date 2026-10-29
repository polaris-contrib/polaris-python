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

"""Verify the lossless example with real HTTP and a fake registry stream."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import ClientSession
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2
from polarismesh_specification.api.v1.traffic_manage import lossless_pb2

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._internal._runtime import verification_directory
from examples.lossless.consumer import main as consumer_demo
from examples.lossless.provider import main as provider_demo
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection


class RegistryStub:
    """Serve a dynamic instance list and lossless rules over the RPC boundary."""

    def __init__(self):
        self.calls = []
        self.instances = []
        self.revision = 0
        rule = lossless_pb2.LosslessRule(namespace="ns", service="svc")
        rule.losslessOnline.warmup.enable = True
        rule.losslessOnline.warmup.intervalSecond = 60
        rule.losslessOnline.warmup.curvature = 1
        self.rules = [rule]

    def record(self, method, request):
        self.calls.append((method, request, threading.get_ident()))

    async def ReportClient(self, request, timeout=None, metadata=()):
        self.record("ReportClient", request)
        return response_pb2.Response(code={"value": 200000})

    def Discover(self, requests, timeout=None, metadata=()):
        async def responses():
            async for request in requests:
                self.record("Discover", request)
                while True:
                    self.revision += 1
                    response = response_pb2.DiscoverResponse(
                        code={"value": 200000}, type=request.type,
                        service=service_pb2.Service(
                            name={"value": request.service.name.value},
                            namespace={"value": request.service.namespace.value},
                            revision={"value": f"revision-{self.revision}"},
                        ),
                    )
                    if request.type == 103:
                        response.losslessRuleList.extend(self.rules)
                    else:
                        response.instances.extend(self.instances)
                    yield response
                    await asyncio.sleep(0.01)
        return responses()

    async def RegisterInstance(self, request, timeout=None, metadata=()):
        self.record("RegisterInstance", request)
        result = service_pb2.Instance()
        result.CopyFrom(request)
        result.id.value = "lossless-provider"
        result.ctime.value = datetime.now(timezone.utc).isoformat()
        self.instances.append(result)
        return response_pb2.Response(code={"value": 200000}, instance=result)

    async def DeregisterInstance(self, request, timeout=None, metadata=()):
        self.record("DeregisterInstance", request)
        self.instances = [
            instance for instance in self.instances
            if not (instance.id.value == request.id.value
                    or (instance.host.value == request.host.value
                        and instance.port.value == request.port.value))
        ]
        return response_pb2.Response(code={"value": 200000})

    def methods(self):
        return [method for method, _, _ in self.calls]


async def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


async def verify():
    stub = RegistryStub()

    async def fake_stub(connection, address):
        return stub

    provider_stop, consumer_stop = asyncio.Event(), asyncio.Event()
    started, provider_info = asyncio.Event(), {}

    async def provider_started(info):
        provider_info.update(info)
        started.set()

    provider_args = SimpleNamespace(
        namespace="ns", service="svc", service_token="token", version="v1",
        host="127.0.0.1", listen_host="127.0.0.1", port=0,
        admin_host="127.0.0.1", admin_port=0, ttl=1,
        config=Path(provider_demo.__file__).with_name("polaris.yaml"),
    )
    consumer_args = SimpleNamespace(
        namespace="ns", service="svc", interval=0.01, timeout=0.5,
        config=Path(consumer_demo.__file__).with_name("polaris.yaml"),
    )

    with patch.object(GrpcConnection, "_stub", fake_stub):
        provider_task = asyncio.create_task(
            provider_demo.run(provider_args, stop=provider_stop, on_started=provider_started)
        )
        consumer_task = None
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            async with ClientSession() as client:
                readiness = f"http://127.0.0.1:{provider_info['admin_port']}/readiness"
                async with client.get(readiness) as response:
                    assert response.status == 503
                    assert await response.text() == "UNREGISTERED"
                assert not any(method == "RegisterInstance" for method in stub.methods())

                await wait_until(lambda: "RegisterInstance" in stub.methods())
                async with client.get(readiness) as response:
                    assert response.status == 200
                    assert await response.text() == "REGISTERED"
                consumer_task = asyncio.create_task(consumer_demo.run(consumer_args, stop=consumer_stop))
                await wait_until(lambda: len(provider_info["http_calls"]) >= 1)

                consumer_stop.set()
                await consumer_task
                provider_stop.set()
                await provider_task
                await wait_until(lambda: not stub.instances)
                assert "DeregisterInstance" in stub.methods()
        finally:
            provider_stop.set()
            consumer_stop.set()
            for task in (provider_task, consumer_task):
                if task is None:
                    continue
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    methods = stub.methods()
    assert methods.count("RegisterInstance") == methods.count("DeregisterInstance") == 1
    assert "Discover" in methods and "ReportClient" in methods
    assert any(method == "Discover" and request.type == 103 for method, request, _ in stub.calls)
    assert any(method == "Discover" and request.type == 1 for method, request, _ in stub.calls)
    print(json.dumps({
        "lossless": "passed", "readiness": True, "http_calls": len(provider_info["http_calls"]),
        "deregistered": True,
    }))


def main():
    with verification_directory(__file__):
        asyncio.run(verify())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
