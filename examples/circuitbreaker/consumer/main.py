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

"""Discover a provider, call /echo and report the local instance circuit result."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import demo_backup_directory, demo_log_options

import argparse
import asyncio
import json
import math
import os
import signal
import threading
import time
import uuid
from contextlib import contextmanager
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from polaris import Configuration, create_consumer_by_config
from polaris.pkg.model.service import CBStatusEnum, GetInstancesRequest, GetOneInstanceRequest, RetStatus, ServiceCallResult

STATE_NAMES = {CBStatusEnum.Closed: "closed", CBStatusEnum.Open: "open", CBStatusEnum.HalfOpen: "half_open"}


def instance_status(instance):
    """Describe the cached instance without allocating a half-open request."""
    status = instance.get_circuit_breaker_status()
    return {"instance_id": instance.get_id(), "host": instance.get_host(), "port": instance.get_port(),
            "healthy": instance.is_healthy(), "circuit_state": STATE_NAMES[status.get_status()],
            "half_open_used": status.get_request_count_after_half_open()}


def invoke_http(instance, timeout, request_id):
    """Read 4xx/5xx bodies too; transport and response-read failures use -1."""
    host = instance.get_host()
    authority = f"[{host}]" if ":" in host else host
    request = Request(f"http://{authority}:{instance.get_port()}/echo", headers={"X-Request-ID": request_id})
    started = time.monotonic()
    code = -1
    try:
        try:
            response = build_opener(ProxyHandler({})).open(request, timeout=timeout)
        except HTTPError as error:
            response = error
        with response:
            body = response.read().decode("utf-8", errors="replace")
            code = response.code
    except (URLError, TimeoutError, OSError, HTTPException) as error:
        body = str(error)
    delay = max(0, int((time.monotonic() - started) * 1000))
    failed = code == -1 or 500 <= code <= 599
    result = ServiceCallResult(instance, RetStatus.RetFail if failed else RetStatus.RetSuccess, code, delay)
    return result, body


class CircuitBreakerCaller:
    """Keep discovery, HTTP invocation and one result report together."""

    def __init__(self, consumer, namespace, service, timeout=2):
        self.consumer = consumer
        self.namespace = namespace
        self.service = service
        self.timeout = timeout

    def select(self):
        """Select through the real SDK route and load-balancing path."""
        instance = self.consumer.get_one_instance(GetOneInstanceRequest(namespace=self.namespace, service=self.service))
        if instance is None:
            raise RuntimeError("No provider instance")
        return instance

    async def async_select(self):
        """Select asynchronously through the context's owner loop."""
        instance = await self.consumer.async_get_one_instance(
            GetOneInstanceRequest(namespace=self.namespace, service=self.service))
        if instance is None:
            raise RuntimeError("No provider instance")
        return instance

    def call_instance(self, instance, request_id=None):
        """Invoke an instance from this context and report its result once."""
        request_id = request_id or uuid.uuid4().hex
        result, body = invoke_http(instance, self.timeout, request_id)
        self.consumer.sync_update_service_call_result(result)
        return self.outcome(instance, result, body, request_id)

    async def async_call_instance(self, instance, request_id=None):
        """Offload blocking HTTP and use the asynchronous SDK report entry."""
        request_id = request_id or uuid.uuid4().hex
        result, body = await asyncio.to_thread(invoke_http, instance, self.timeout, request_id)
        await self.consumer.async_update_service_call_result(result)
        return self.outcome(instance, result, body, request_id)

    def call(self, request_id=None):
        """Discover, invoke and report a synchronous business call."""
        return self.call_instance(self.select(), request_id)

    async def async_call(self, request_id=None):
        """Discover, invoke and report an asynchronous business call."""
        return await self.async_call_instance(await self.async_select(), request_id)

    @staticmethod
    def outcome(instance, result, body, request_id):
        """Return the original result alongside the resulting local circuit state."""
        return {**instance_status(instance), "ret_code": result.ret_code, "delay_ms": result.delay,
                "request_id": request_id, "body": body}

    def snapshot(self):
        """Read every cached instance, including open and half-open instances."""
        response = self.consumer.get_all_instances(GetInstancesRequest(namespace=self.namespace, service=self.service))
        return [instance_status(node) for node in response.instances]


@contextmanager
def running_caller(caller, *, host="0.0.0.0", port=18080):
    """Serve calls and snapshots, then drain handlers before context destruction."""
    class CallerHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            try:
                if path == "/echo":
                    value = caller.call(self.headers.get("X-Request-ID"))
                    self.send_json(502 if value["ret_code"] == -1 else value["ret_code"], value)
                elif path == "/instances":
                    self.send_json(200, caller.snapshot())
                else:
                    self.send_json(404, {"error": "not found"})
            except Exception as error:
                self.send_json(503, {"error": str(error)})

        def send_json(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer((host, port), CallerHandler)
    serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    started = False
    try:
        serving.start()
        started = True
        yield server
    finally:
        if started:
            server.shutdown()
            serving.join()
        server.server_close()


def main(argv=None):
    """Run the registry-backed caller only with explicit opt-in."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--service", default="CircuitBreakerCallee")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--call-timeout", type=float, default=2)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("polaris.yaml"))
    args = parser.parse_args(argv)
    if not args.namespace or not args.service or not 0 <= args.port <= 65535:
        parser.error("Invalid namespace, service or port")
    if not math.isfinite(args.call_timeout) or args.call_timeout <= 0:
        parser.error("--call-timeout must be finite and positive")
    if os.getenv("POLARIS_E2E") != "1":
        print(json.dumps({"skipped": True, "reason": "Set POLARIS_E2E=1 to connect to Polaris"}))
        return 0
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    config = Configuration.from_file(str(args.config))
    config.get_consumer().get_local_cache().persist_dir = str(
        demo_backup_directory(__file__, component="consumer")
    )
    consumer = create_consumer_by_config(
        config,
        log_options=demo_log_options(__file__, component="consumer"),
    )
    try:
        caller = CircuitBreakerCaller(consumer, args.namespace, args.service, args.call_timeout)
        with running_caller(caller, port=args.port) as server:
            print(json.dumps({"started": True, "port": server.server_address[1]}), flush=True)
            stop.wait()
    finally:
        consumer.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
