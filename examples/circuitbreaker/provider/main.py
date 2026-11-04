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

"""Register an HTTP provider with switchable success and failure responses."""

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
import json
import os
import signal
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from polaris import Configuration, create_provider_by_config
from polaris.pkg.model.server import InstanceDeRegisterRequest, InstanceRegisterRequest


class ProviderState:
    """Hold a thread-safe HTTP status independent of registry health."""

    def __init__(self, status=200):
        self.lock = threading.Lock()
        self.status = status

    def get_status(self):
        """Read the status used by the next echo response."""
        with self.lock:
            return self.status

    def switch(self, query):
        """Apply one validated fault toggle or explicit HTTP status."""
        values = parse_qs(query, keep_blank_values=True)
        if set(values) not in ({"openError"}, {"status"}) or any(len(v) != 1 for v in values.values()):
            raise ValueError("Supply exactly one openError=true/false or status=200..599")
        if "openError" in values:
            value = values["openError"][0]
            if value not in ("true", "false"):
                raise ValueError("openError must be true or false")
            status = 500 if value == "true" else 200
        else:
            status = int(values["status"][0])
            if not 200 <= status <= 599:
                raise ValueError("status must be in [200, 599]")
        with self.lock:
            self.status = status
        return status


def handler_for(state, request):
    """Bind an HTTP handler to one provider's state and advertised address."""
    class ProviderHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path)
            if path.path == "/switch":
                try:
                    status = state.switch(path.query)
                    self.send_json(200, {"status": status})
                except ValueError as error:
                    self.send_json(400, {"error": str(error)})
            elif path.path == "/echo":
                status = state.get_status()
                self.send_json(status, {
                    "status": status, "host": request.host, "port": request.port,
                    "service": request.service, "request_id": self.headers.get("X-Request-ID", ""),
                })
            else:
                self.send_json(404, {"error": "not found"})

        def send_json(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    return ProviderHandler


@contextmanager
def running_provider(config, request, *, status=200, listen_host="0.0.0.0", log_options=None):
    """Own the HTTP listener, automatic heartbeat and deregistration lifecycle."""
    server = ThreadingHTTPServer((listen_host, request.port), handler_for(ProviderState(status), request))
    request.port = server.server_address[1]
    serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    provider = None
    response = None
    started = False
    try:
        serving.start()
        started = True
        provider = create_provider_by_config(config, log_options=log_options)
        response = provider.register_instance(request)
        yield server, provider, response
    finally:
        try:
            if started:
                server.shutdown()
                serving.join()
            server.server_close()
        finally:
            if provider is not None:
                try:
                    if response is not None:
                        provider.deregister(InstanceDeRegisterRequest(
                            request.service, request.service_token, request.namespace,
                            request.host, request.port, response.instance_id,
                        ))
                        print(json.dumps({"deregistered": response.instance_id}), flush=True)
                finally:
                    provider.destroy()


def main(argv=None):
    """Run the registry-backed provider only with explicit opt-in."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--service", default="CircuitBreakerCallee")
    parser.add_argument("--service-token", default=os.getenv("POLARIS_SERVICE_TOKEN", ""))
    parser.add_argument("--host", help="Explicit advertised business address; defaults to the Polaris route source IP")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--status", type=int, default=200)
    parser.add_argument("--ttl", type=int, default=5)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("polaris.yaml"))
    args = parser.parse_args(argv)
    if not args.namespace or not args.service:
        parser.error("--namespace and --service must not be empty")
    if not 0 <= args.port <= 65535 or not 200 <= args.status <= 599 or not 0 < args.ttl <= 0xFFFFFFFF:
        parser.error("Invalid port, HTTP status or heartbeat TTL")
    if os.getenv("POLARIS_E2E") != "1":
        print(json.dumps({"skipped": True, "reason": "Set POLARIS_E2E=1 to connect to Polaris"}))
        return 0
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    config = Configuration.from_file(str(args.config))
    configure_e2e_event_reporting(config)
    if not args.host:
        args.host = get_local_host(config.get_global().get_server_connector().get_addresses()[0])
    if not args.host:
        parser.error("--host must not be empty")
    config.get_consumer().get_local_cache().persist_dir = str(
        demo_backup_directory(__file__, component="provider")
    )
    request = InstanceRegisterRequest(args.service, args.service_token, args.namespace,
                                      args.host, args.port, protocol="http", ttl=args.ttl)
    with running_provider(
        config,
        request,
        status=args.status,
        listen_host=args.listen_host,
        log_options=demo_log_options(__file__, component="provider"),
    ) as (server, _, response):
        print(json.dumps({"registered": response.instance_id, "host": args.host,
                          "port": server.server_address[1], "status": args.status}), flush=True)
        stop.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
