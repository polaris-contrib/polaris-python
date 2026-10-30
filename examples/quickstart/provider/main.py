#!/usr/bin/python
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

"""Run an HTTP provider, register it, and deregister it on shutdown."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import configure_e2e_event_reporting, demo_backup_directory, demo_log_options

import argparse
import json
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from examples._internal._runtime import get_local_host
from polaris.api.provider import ProviderAPI, create_provider_by_config
from polaris.pkg.config.api import Configuration
from polaris.pkg.model.server import InstanceDeRegisterRequest, InstanceRegisterRequest


class ProviderHandler(BaseHTTPRequestHandler):
    state = {}

    def do_GET(self):
        if self.path.split("?", 1)[0] != "/echo":
            self.send_error(404)
            return
        body = (
            f"Hello, I'm {self.state['service']} Provider, "
            f"My host : {self.state['host']}:{self.state['port']}"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"provider request: {self.address_string()} {format % args}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--service", default="DiscoverEchoServer")
    parser.add_argument("--service-token", required=True)
    parser.add_argument("--port", type=int, default=0, help="listening port; 0 selects an ephemeral port")
    parser.add_argument("--ttl", type=int, default=1)
    parser.add_argument("--config", help="Path to polaris.yaml; defaults to the adjacent polaris.yaml")
    args = parser.parse_args()
    if not args.namespace or not args.service:
        parser.error("--namespace and --service must not be empty")
    if not 0 < args.ttl <= 0xFFFFFFFF:
        parser.error("--ttl must be a positive uint32 number of seconds")
    if not 0 <= args.port < 65536:
        parser.error("--port must be in range [0, 65535]")
    return args


def main() -> int:
    args = parse_args()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    provider = None
    server = None
    response = None
    host = ""
    try:
        config_path = args.config or Path(__file__).with_name("polaris.yaml")
        config = Configuration.from_file(str(config_path))
        configure_e2e_event_reporting(config)
        config.get_consumer().get_local_cache().persist_dir = str(
            demo_backup_directory(__file__, component="provider")
        )
        provider = create_provider_by_config(
            config,
            log_options=demo_log_options(__file__, component="provider"),
        )
        connector = provider.context.get_config().get_global().get_server_connector()
        host = get_local_host(connector.get_addresses()[0])

        server = ThreadingHTTPServer(("0.0.0.0", args.port), ProviderHandler)
        server.daemon_threads = True
        port = server.server_address[1]
        ProviderHandler.state = {"service": args.service, "host": host, "port": port}

        request = InstanceRegisterRequest(
            args.service, args.service_token, args.namespace, host, port,
            protocol="http", version="1.0.0", ttl=args.ttl,
        )
        response = provider.register_instance(request)
        print(json.dumps({
            "registered": True, "instance_id": response.instance_id,
            "host": host, "port": port, "listen": f"0.0.0.0:{port}",
        }), flush=True)

        serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        serving.start()
        while not stop.is_set():
            stop.wait(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        if provider is not None and response is not None:
            provider.deregister(InstanceDeRegisterRequest(
                args.service, args.service_token, args.namespace, host,
                ProviderHandler.state["port"], response.instance_id,
            ))
            print(json.dumps({"deregistered": True, "instance_id": response.instance_id}), flush=True)
        if server is not None:
            server.shutdown()
            server.server_close()
        if provider is not None:
            provider.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
