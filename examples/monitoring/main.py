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

"""Report real HTTP invocations and export Prometheus metrics."""

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from aiohttp import ClientSession, web

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._support import (
    demo_backup_directory,
    demo_log_options,
    get_local_host,
    wait_for_operation_or_stop,
    wait_for_stop,
)
from polaris import Configuration, ConsumerAPI, ProviderAPI, SDKError, init_context_by_config
from polaris.pkg.model.server import InstanceDeRegisterRequest, InstanceRegisterRequest
from polaris.pkg.model.service import (
    GetInstancesRequest,
    RetStatus,
    ServiceCallResult,
    ServiceInfo,
)


@contextmanager
def stop_on_signals(loop, stop):
    previous = {}

    def request_stop(_signum, _frame):
        loop.call_soon_threadsafe(stop.set)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, request_stop)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


async def wait_for_instance(consumer, namespace, service, instance_id, stop):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if stop.is_set():
            return None
        try:
            completed, snapshot = await wait_for_operation_or_stop(
                stop,
                consumer.async_get_all_instances(
                    GetInstancesRequest(namespace=namespace, service=service),
                ),
            )
        except SDKError:
            snapshot = None
        else:
            if not completed or stop.is_set():
                return None
        if snapshot is not None:
            node = next(
                (item for item in snapshot.instances if item.get_id() == instance_id),
                None,
            )
            if node is not None:
                return node
        if await wait_for_stop(stop, 0.2):
            return None
    if stop.is_set():
        return None
    raise RuntimeError("registered echo instance did not become discoverable")


async def run(args):
    if not args.host:
        args.host = get_local_host(args.server.split(",", 1)[0].strip())

    async def echo(request):
        return web.Response(
            text="echo",
            status=int(request.query.get("status", "200")),
        )

    app = web.Application()
    app.router.add_get("/echo", echo)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    context = None
    provider = None
    registered = None
    stop = asyncio.Event()
    try:
        site = web.TCPSite(runner, args.host, 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]

        config = Configuration()
        config.set_default()
        config.get_global().get_server_connector().addresses = args.server.split(",")
        config.get_global().get_server_connector().token = os.getenv("POLARIS_TOKEN", "")
        config.get_global().get_admin().host = "127.0.0.1"
        config.get_global().get_admin().port = args.metrics_port
        options = config.get_global().get_stat_reporter().get_prometheus()
        options.type = args.mode
        options.address = args.push_address
        options.push_interval = args.push_interval
        config.get_consumer().get_local_cache().persist_dir = str(
            demo_backup_directory(__file__)
        )
        context = await asyncio.to_thread(
            init_context_by_config,
            config,
            log_options=demo_log_options(__file__),
        )
        provider, consumer = ProviderAPI(context), ConsumerAPI(context)
        with stop_on_signals(asyncio.get_running_loop(), stop):
            registered = await provider.async_register_instance(InstanceRegisterRequest(
                namespace=args.namespace,
                service=args.service,
                service_token=args.token,
                host=args.host,
                port=port,
                protocol="http",
                ttl=5,
            ))
            node = await wait_for_instance(
                consumer,
                args.namespace,
                args.service,
                registered.instance_id,
                stop,
            )
            if node is None:
                return
            authority = f"[{node.get_host()}]" if ":" in node.get_host() else node.get_host()
            async with ClientSession() as client:
                for status in (200, 503, 200):
                    started = time.monotonic()
                    async with client.get(
                        f"http://{authority}:{node.get_port()}/echo?status={status}"
                    ) as response:
                        await response.read()
                        code = response.status
                    await consumer.async_update_service_call_result(ServiceCallResult(
                        called_instance=node,
                        method="/echo",
                        ret_code=code,
                        ret_status=RetStatus.RetSuccess if code < 500 else RetStatus.RetFail,
                        delay=int((time.monotonic() - started) * 1000),
                        caller_service=ServiceInfo("demo-caller", args.namespace),
                        labels="env=demo",
                    ))
                if args.duration:
                    if await wait_for_stop(stop, args.duration):
                        return
                if stop.is_set():
                    return
                metrics_url = (
                    f"http://127.0.0.1:{context.engine.stat_reporter.port}/metric"
                    if args.mode == "pull"
                    else None
                )
                result = {
                    "mode": args.mode,
                    "metrics_url": metrics_url,
                    "calls": 3,
                    "host": args.host,
                    "port": port,
                }
                if args.mode == "push":
                    result["pushes"] = context.engine.stat_reporter.push_count
                print(json.dumps(result), flush=True)
                if metrics_url:
                    async with client.get(metrics_url) as response:
                        metrics = await response.text()
                    if 'callee_method="/echo"' not in metrics:
                        raise RuntimeError("no aggregated /echo metrics; increase --duration")
                    print(metrics, end="", flush=True)
                if args.keep_running:
                    await stop.wait()
    finally:
        try:
            if registered is not None:
                await provider.async_deregister_instance(InstanceDeRegisterRequest(
                    namespace=args.namespace,
                    service=args.service,
                    service_token=args.token,
                    host=args.host,
                    port=port,
                    instance_id=registered.instance_id,
                ))
        finally:
            try:
                if context is not None:
                    await asyncio.to_thread(context.destroy)
            finally:
                await runner.cleanup()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("POLARIS_SERVER_ADDRESS", "127.0.0.1:8091"))
    parser.add_argument("--token", default=os.getenv("POLARIS_SERVICE_TOKEN", ""))
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--service", default="demo-monitoring")
    parser.add_argument("--host", help="advertised and listening IP")
    parser.add_argument("--mode", choices=("pull", "push"), default="pull")
    parser.add_argument("--metrics-port", type=int, default=0)
    parser.add_argument("--push-address", action="append", default=[])
    parser.add_argument("--push-interval", type=int, default=10000)
    parser.add_argument("--duration", type=float, default=31)
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args(argv)
    if args.duration < 0:
        parser.error("duration must be nonnegative")
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
