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

"""Verify real loopback HTTP calls, pull metrics and Pushgateway payloads."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from prometheus_client.parser import text_string_to_metric_families

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._internal._ai_stub import AIStub
from examples._internal._runtime import verification_directory
from examples.monitoring import main as demo
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection


async def verify():
    stub, received = AIStub(), []
    async def fake_stub(connection, address):
        return stub
    async def push(request):
        received.append((request.path, await request.text()))
        return web.Response()

    app = web.Application()
    app.router.add_post("/{path:.*}", push)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    parser_args = dict(server="offline:8091", namespace="ns", service="echo", token="token",
                       host="127.0.0.1", metrics_port=0, push_interval=1000)
    from types import SimpleNamespace
    try:
        with patch.object(GrpcConnection, "_stub", fake_stub), \
                patch("polaris.plugin.stat_reporter.prometheus.PULL_INTERVAL_SECONDS", 0.1):
            await demo.run(SimpleNamespace(**parser_args, mode="pull", push_address=[], duration=0.15))
            await demo.run(SimpleNamespace(**parser_args, mode="push",
                                          push_address=[f"127.0.0.1:{port}"], duration=1.1))
        assert received and received[0][0].startswith("/metrics/job/polaris-client/instance/")
        samples = [sample for family in text_string_to_metric_families(received[0][1])
                   for sample in family.samples if sample.labels.get("callee_method") == "/echo"]
        assert sum(sample.value for sample in samples if sample.name == "upstream_rq_total") == 3
        assert sum(sample.value for sample in samples if sample.name == "upstream_rq_success") == 2
        assert not stub.instances
        print(json.dumps({"monitoring": "passed", "pull": True, "push": True, "calls": 3}))
    finally:
        await runner.cleanup()


def main():
    with verification_directory(__file__):
        asyncio.run(verify())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
