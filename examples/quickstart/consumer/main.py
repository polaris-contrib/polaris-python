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

"""Run an HTTP consumer that discovers and calls a provider synchronously."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import demo_backup_directory, demo_log_options

import argparse
import json
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from polaris.api.consumer import ConsumerAPI, create_consumer_by_config
from polaris.pkg.config.api import Configuration
from polaris.pkg.model.service import GetOneInstanceRequest, RetStatus, ServiceCallResult


class ConsumerHandler(BaseHTTPRequestHandler):
    consumer = None
    namespace = ""
    service = ""
    timeout = 2.0

    def _call(self, namespace: str, service: str) -> tuple[bytes, int]:
        instance = self.consumer.get_one_instance(GetOneInstanceRequest(
            namespace=namespace, service=service, timeout=5000, use_discover_cache=True,
        ))
        if instance is None:
            raise RuntimeError("no available provider instance")

        url = f"http://{instance.get_host()}:{instance.get_port()}/echo"
        started = time.monotonic()
        try:
            with urlopen(url, timeout=self.timeout) as response:
                status = response.status
                body = response.read()
        except HTTPError as error:
            status = error.code
            body = error.read()
        except (URLError, TimeoutError, OSError) as error:
            status = 500
            body = str(error).encode()

        result = ServiceCallResult(
            called_instance=instance,
            ret_status=RetStatus.RetSuccess if 200 <= status < 300 else RetStatus.RetFail,
            ret_code=status,
            delay=max(1, int((time.monotonic() - started) * 1000)),
        )
        self.consumer.sync_update_service_call_result(result)
        return body, status

    def _send(self, status: int, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?", 1)[0] != "/echo":
            self.send_error(404)
            return
        try:
            body, status = self._call(self.namespace, self.service)
            self._send(200 if 200 <= status < 300 else 502, body)
        except Exception as error:
            self._send(500, str(error).encode())

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/echo-with-body":
            self.send_error(404)
            return
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            namespace = request["namespace"]
            service = request["service"]
            if not namespace or not service:
                raise ValueError("namespace and service are required")
            body, status = self._call(namespace, service)
            self._send(200 if 200 <= status < 300 else 502, body)
        except Exception as error:
            self._send(400, str(error).encode())

    def log_message(self, format, *args):
        print(f"consumer request: {self.address_string()} {format % args}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--service", default="DiscoverEchoServer")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--call-timeout", type=float, default=2.0)
    parser.add_argument("--config", help="Path to polaris.yaml; defaults to the adjacent polaris.yaml")
    args = parser.parse_args()
    if not args.namespace or not args.service:
        parser.error("--namespace and --service must not be empty")
    if not 0 < args.port < 65536:
        parser.error("--port must be in range (0, 65536)")
    if args.call_timeout <= 0:
        parser.error("--call-timeout must be positive")
    return args


def main() -> int:
    args = parse_args()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    consumer = None
    server = None
    try:
        config_path = args.config or Path(__file__).with_name("polaris.yaml")
        config = Configuration.from_file(str(config_path))
        config.get_consumer().get_local_cache().persist_dir = str(
            demo_backup_directory(__file__, component="consumer")
        )
        consumer = create_consumer_by_config(
            config,
            log_options=demo_log_options(__file__, component="consumer"),
        )
        ConsumerHandler.consumer = consumer
        ConsumerHandler.namespace = args.namespace
        ConsumerHandler.service = args.service
        ConsumerHandler.timeout = args.call_timeout

        server = ThreadingHTTPServer(("0.0.0.0", args.port), ConsumerHandler)
        server.daemon_threads = True
        print(json.dumps({"started": True, "listen": f"0.0.0.0:{server.server_address[1]}"}), flush=True)
        serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        serving.start()
        while not stop.is_set():
            stop.wait(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if consumer is not None:
            consumer.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
