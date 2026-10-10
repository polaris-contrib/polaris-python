"""Register an HTTP provider whose failures can open a Polaris circuit."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from polaris_python import Config, ProviderAPI, ServiceInstance
from polaris_python.api.factory import APIFactory


class EchoHandler(BaseHTTPRequestHandler):
    """Provider endpoint with a runtime-switchable error response."""

    error_mode = threading.Event()
    service = "CircuitBreakerCallee"
    host = "127.0.0.1"
    port = 0

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        parsed = urlparse(self.path)
        if parsed.path == "/switch":
            value = parse_qs(parsed.query).get("openError", [""])[0].lower()
            if value in {"true", "1", "yes", "on"}:
                self.error_mode.set()
            elif value in {"false", "0", "no", "off"}:
                self.error_mode.clear()
            else:
                self.send_error(400, "openError must be true or false")
                return
            self._write(200, f"openError={self.error_mode.is_set()}\n".encode())
            return
        if parsed.path == "/health":
            self._write(200, b"ok\n")
            return
        if parsed.path != "/echo":
            self.send_error(404)
            return
        if self.error_mode.is_set():
            body = f"provider failure at {self.host}:{self.port}\n".encode()
            self._write(500, body)
        else:
            body = f"Hello, I'm {self.service} Provider, host={self.host}:{self.port}\n".encode()
            self._write(200, body)

    def _write(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        logging.getLogger(__name__).info(format, *args)


def main() -> None:
    """Start one provider; launch this file twice for a healthy and failing instance."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="CircuitBreakerCallee")
    parser.add_argument("--namespace", default=os.getenv("POLARIS_NAMESPACE", "default"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--initial-error", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = Config.from_env()
    context = APIFactory.create_context(config)
    provider: ProviderAPI = APIFactory.create_provider_api(context)
    server = ThreadingHTTPServer((args.host, args.port), EchoHandler)
    instance = ServiceInstance(
        service=args.service,
        namespace=args.namespace or config.namespace or "default",
        host=args.host,
        port=server.server_address[1],
        protocol="http",
        version="v1",
        ttl_seconds=10,
    )
    if args.initial_error:
        EchoHandler.error_mode.set()
    EchoHandler.service = args.service
    EchoHandler.host = instance.host
    EchoHandler.port = instance.port
    stop = threading.Event()
    registered = provider.register_instance(instance)
    logging.info("registered %s/%s at %s:%s", registered.namespace, registered.service, registered.host, registered.port)

    def stop_server(signum: int, _frame: object) -> None:
        logging.info("received signal %s", signum)
        stop.set()

    signal.signal(signal.SIGINT, stop_server)
    signal.signal(signal.SIGTERM, stop_server)
    server_thread = threading.Thread(target=server.serve_forever, name="circuitbreaker-http", daemon=True)
    heartbeat_thread = threading.Thread(target=_heartbeat_loop, args=(provider, registered, stop), daemon=True)
    server_thread.start()
    heartbeat_thread.start()
    logging.info("circuit-breaker provider listening on http://%s:%s/echo error=%s", args.host, instance.port, args.initial_error)
    try:
        stop.wait()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()
        heartbeat_thread.join()
        provider.deregister_instance(registered)
        context.destroy()


def _heartbeat_loop(provider: ProviderAPI, instance: ServiceInstance, stop: threading.Event) -> None:
    while not stop.wait(5):
        provider.heartbeat(instance)


if __name__ == "__main__":
    main()
