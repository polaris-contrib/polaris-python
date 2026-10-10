"""Register a small HTTP service in Polaris."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from polaris_python import Config, ServiceInstance
from polaris_python.api.factory import APIFactory


class EchoHandler(BaseHTTPRequestHandler):
    """Return a response identifying this provider instance."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path != "/echo":
            self.send_error(404)
            return
        body = f"Hello from Polaris Python provider {self.server.server_address[0]}:{self.server.server_address[1]}\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        logging.getLogger(__name__).info(format, *args)


async def main() -> None:
    """Start the HTTP server and maintain its Polaris registration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="polaris-python-demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--resource-type", default="agent")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = Config.from_env()
    context = APIFactory.create_context(config)
    provider = APIFactory.create_provider_api(context)
    http_server = ThreadingHTTPServer((args.host, args.port), EchoHandler)
    http_task = asyncio.create_task(asyncio.to_thread(http_server.serve_forever))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            pass

    instance = ServiceInstance(
        service=args.service,
        namespace=config.namespace,
        host=args.host,
        port=http_server.server_address[1],
        resource_type=args.resource_type,
        protocol="http",
        version="v1",
        ttl_seconds=10,
    )
    registered = await provider.async_register_instance(instance)
    logging.info("registered %s/%s at %s:%s", registered.namespace, registered.service, registered.host, registered.port)
    try:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                await provider.async_heartbeat(registered)
    finally:
        await provider.async_deregister_instance(registered)
        http_server.shutdown()
        await http_task
        await context.async_destroy()
        logging.info("provider stopped")


if __name__ == "__main__":
    asyncio.run(main())
