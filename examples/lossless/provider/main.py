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

"""Start an echo endpoint and register it through lossless online."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import (
    configure_e2e_event_reporting,
    demo_backup_directory,
    demo_log_options,
    get_local_host,
)

import argparse
import asyncio
import json
import os
import signal

from aiohttp import ClientSession, web

from polaris import Configuration, create_provider_by_config
from polaris.pkg.model.server import InstanceRegisterRequest


async def run(args, stop=None, on_started=None):
    """Own the HTTP endpoint, delayed registration and lossless shutdown."""
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async def echo(request):
        request.app["calls"].append(request.headers.get("X-Request-ID", ""))
        return web.json_response({
            "host": request.app["host"], "port": request.app["port"],
            "status": 200,
        })

    app = web.Application()
    app["calls"] = []
    app.router.add_get("/echo", echo)
    app.router.add_get("/ready", lambda _: web.Response(text="ready"))
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, args.listen_host, args.port)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    app["port"] = port

    config = Configuration.from_file(str(args.config))
    configure_e2e_event_reporting(config)
    config.get_global().get_admin().host = args.admin_host
    config.get_global().get_admin().port = args.admin_port
    config.get_consumer().get_local_cache().persist_dir = str(
        demo_backup_directory(__file__, component="provider")
    )
    if not args.host:
        args.host = get_local_host(config.get_global().get_server_connector().get_addresses()[0])
    app["host"] = args.host

    provider = create_provider_by_config(
        config, log_options=demo_log_options(__file__, component="provider")
    )
    request = InstanceRegisterRequest(
        service=args.service, service_token=args.service_token, namespace=args.namespace,
        host=args.host, port=port, protocol="http", ttl=args.ttl,
        auto_heartbeat=True, metadata={"version": args.version},
    )
    try:
        await provider.async_lossless_register(request)
        admin_port = provider.context.engine.admin_server.port
        started = {
            "started": True, "host": args.host, "port": port, "admin_port": admin_port,
            "readiness_url": f"http://{args.admin_host}:{admin_port}/readiness",
            "offline_url": f"http://{args.admin_host}:{admin_port}/offline",
        }
        print(json.dumps(started), flush=True)
        if on_started is not None:
            await on_started({**started, "http_calls": app["calls"]})
        await stop.wait()
        await provider.async_lossless_deregister(request)
        print(json.dumps({"deregistered": request.instance_id}), flush=True)
    finally:
        await runner.cleanup()
        provider.destroy()


def main(argv=None):
    """Parse arguments and run the provider."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--service", default="LosslessEchoServer")
    parser.add_argument("--service-token", default=os.getenv("POLARIS_SERVICE_TOKEN", ""))
    parser.add_argument("--version", default="v1")
    parser.add_argument("--host", help="Advertised host; defaults to the Polaris route source IP")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--admin-host", default="127.0.0.1")
    parser.add_argument("--admin-port", type=int, default=28080)
    parser.add_argument("--ttl", type=int, default=5)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("polaris.yaml"))
    args = parser.parse_args(argv)
    if not args.namespace or not args.service:
        parser.error("--namespace and --service must not be empty")
    if not 0 <= args.port <= 65535 or not 0 <= args.admin_port <= 65535:
        parser.error("ports must be in [0, 65535]")
    if not 0 < args.ttl <= 0xFFFFFFFF:
        parser.error("--ttl must be a positive uint32")
    if os.getenv("POLARIS_E2E") != "1":
        print(json.dumps({"skipped": True, "reason": "Set POLARIS_E2E=1 to connect to Polaris"}))
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
