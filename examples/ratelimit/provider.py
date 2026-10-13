"""Register an HTTP provider and enforce Polaris rate-limit rules."""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from polaris_python import Config, LimitAPI, ProviderAPI, QuotaRequest, ServiceInstance
from polaris_python.api.factory import APIFactory


class EchoHandler(BaseHTTPRequestHandler):
    """Apply a Polaris quota before serving the echo response."""

    limiter: LimitAPI
    namespace: str
    service: str
    host: str
    port: int

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path not in {"/echo", "/health"}:
            self.send_error(404)
            return
        quota = self.limiter.get_quota(
            QuotaRequest(
                namespace=self.namespace,
                service=self.service,
                method=self.path,
                labels={key.lower(): value for key, value in self.headers.items()},
            )
        )
        try:
            if not quota.allowed:
                body = b"Too Many Requests\n"
                self.send_response(429)
            else:
                body = f"Hello, I'm RateLimitEchoServer Provider, My host : {self.host}:{self.port}\n".encode()
                self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            quota.release()

    def log_message(self, format: str, *args: object) -> None:
        logging.getLogger(__name__).info(format, *args)


def main() -> None:
    """Start the provider, register it, and deregister on shutdown."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="RateLimitEchoServer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = Config.from_env()
    context = APIFactory.create_context(config)
    provider: ProviderAPI = APIFactory.create_provider_api(context)
    limiter = APIFactory.create_limit_api(context)
    server = ThreadingHTTPServer((args.host, args.port), EchoHandler)
    instance = ServiceInstance(
        service=args.service,
        namespace=config.namespace,
        host=args.host,
        port=server.server_address[1],
        protocol="http",
        version="v1",
        ttl_seconds=10,
    )
    EchoHandler.limiter = limiter
    EchoHandler.namespace = instance.namespace
    EchoHandler.service = instance.service
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
    server_thread = threading.Thread(target=server.serve_forever, name="ratelimit-http", daemon=True)
    server_thread.start()
    logging.info("rate-limit provider listening on http://%s:%s/echo", args.host, instance.port)
    try:
        stop.wait()
    finally:
        server.shutdown()
        server_thread.join()
        provider.deregister_instance(registered)
        context.destroy()


if __name__ == "__main__":
    main()
