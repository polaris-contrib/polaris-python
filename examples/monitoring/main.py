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

"""Report real HTTP invocations and export pull or push Prometheus metrics."""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from aiohttp import ClientSession, web

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._internal._runtime import (
    configure_e2e_event_reporting,
    demo_backup_directory,
    demo_log_options,
    get_local_host,
)
from polaris import Configuration, ConsumerAPI, ProviderAPI, init_context_by_config
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.pkg.model.server import InstanceRegisterRequest, InstanceDeRegisterRequest
from polaris.pkg.model.service import GetOneInstanceRequest, RetStatus, ServiceCallResult, ServiceInfo


async def run(args):
    """Own one echo endpoint, registration, HTTP calls and the metrics context."""
    if not args.host:
        args.host = get_local_host(args.server.split(",", 1)[0].strip())

    async def echo(request):
        return web.Response(text="echo", status=int(request.query.get("status", "200")))

    app = web.Application()
    app.router.add_get("/echo", echo)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, args.host, 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    context, registered = None, None
    try:
        config = Configuration()
        config.set_default()
        configure_e2e_event_reporting(config)
        config.get_global().get_server_connector().addresses = args.server.split(",")
        config.get_global().get_server_connector().token = os.getenv("POLARIS_TOKEN", "")
        config.get_global().get_admin().host = "127.0.0.1"
        config.get_global().get_admin().port = args.metrics_port
        options = config.get_global().get_stat_reporter().get_prometheus()
        options.type = args.mode
        options.address = args.push_address
        options.push_interval = args.push_interval
        config.get_consumer().get_local_cache().persist_dir = str(demo_backup_directory(__file__))
        context = await asyncio.to_thread(init_context_by_config, config, log_options=demo_log_options(__file__))
        provider, consumer = ProviderAPI(context), ConsumerAPI(context)
        registered = await provider.async_register_instance(InstanceRegisterRequest(
            namespace=args.namespace, service=args.service, service_token=args.token,
            host=args.host, port=port, protocol="http", ttl=5))
        deadline = time.monotonic() + 40
        while True:
            try:
                node = await consumer.async_get_one_instance(GetOneInstanceRequest(
                    namespace=args.namespace, service=args.service))
            except SDKError as error:
                retryable = (error.err_code == ErrorCode.ErrCodeAPITimeoutError
                              or (error.err_code == ErrorCode.ErrCodeServerError
                                  and "not found" in error.msg.lower()))
                if not retryable:
                    raise
                node = None
            if node is not None:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Registered echo instance did not become discoverable")
            await asyncio.sleep(0.2)
        async with ClientSession() as client:
            for status in (200, 503, 200):
                node = await consumer.async_get_one_instance(GetOneInstanceRequest(
                    namespace=args.namespace, service=args.service))
                if node is None:
                    raise RuntimeError("No available echo endpoint")
                started, code, success = time.monotonic(), -1, False
                try:
                    authority = f"[{node.get_host()}]" if ":" in node.get_host() else node.get_host()
                    async with client.get(f"http://{authority}:{node.get_port()}/echo?status={status}") as response:
                        await response.read()
                        code, success = response.status, response.status < 500
                finally:
                    await consumer.async_update_service_call_result(ServiceCallResult(
                        called_instance=node, method="/echo", ret_code=code,
                        ret_status=RetStatus.RetSuccess if success else RetStatus.RetFail,
                        delay=int((time.monotonic() - started) * 1000),
                        caller_service=ServiceInfo("demo-caller", args.namespace), labels="env=demo"))
            url = f"http://127.0.0.1:{context.engine.stat_reporter.port}/metric" if args.mode == "pull" else None
            await asyncio.sleep(args.duration)
            result = {
                "mode": args.mode,
                "metrics_url": url,
                "calls": 3,
                "host": args.host,
                "port": port,
            }
            if args.mode == "push":
                result["pushes"] = context.engine.stat_reporter.push_count
            print(json.dumps(result), flush=True)
            if url:
                async with client.get(url) as response:
                    metrics = await response.text()
                    if 'callee_method="/echo"' not in metrics:
                        raise RuntimeError("No aggregated HTTP call metrics; allow at least 30 seconds")
                    print(metrics, end="", flush=True)
        result = {"mode": args.mode, "calls": 3, "host": args.host, "port": port}
        if args.mode == "push":
            result["pushes"] = context.engine.stat_reporter.push_count
        return result
    finally:
        try:
            if context is not None and registered is not None:
                await ProviderAPI(context).async_deregister_instance(InstanceDeRegisterRequest(
                    namespace=args.namespace, service=args.service, service_token=args.token,
                    host=args.host, port=port, instance_id=registered.instance_id))
        finally:
            if context is not None:
                await asyncio.to_thread(context.destroy)
            await runner.cleanup()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("POLARIS_SERVER_ADDRESS", "127.0.0.1:8091"))
    parser.add_argument("--token", default=os.getenv("POLARIS_SERVICE_TOKEN", ""))
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--service", default="demo-monitoring")
    parser.add_argument("--host", help="Advertised and listening IP; defaults to the Polaris route source IP")
    parser.add_argument("--mode", choices=["pull", "push"], default="pull")
    parser.add_argument("--metrics-port", type=int, default=0)
    parser.add_argument("--push-address", action="append", default=[])
    parser.add_argument("--push-interval", type=int, default=10000)
    parser.add_argument("--duration", type=float, default=31)
    args = parser.parse_args(argv)
    if args.duration < 0:
        parser.error("duration must be nonnegative")
    if os.getenv("POLARIS_E2E") != "1":
        print("Set POLARIS_E2E=1 to register an echo endpoint and report real HTTP calls.")
        return 0
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
