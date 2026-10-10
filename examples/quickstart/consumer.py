"""Discover a provider and expose a local HTTP proxy."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

from polaris_python import Config
from polaris_python.api.consumer import ConsumerAPI
from polaris_python.api.factory import APIFactory


def _fetch(url: str) -> bytes:
    """Fetch a provider response without blocking the asyncio event loop."""
    with urlopen(url, timeout=3) as response:
        return response.read()


class ProxyHandler(BaseHTTPRequestHandler):
    """Forward /echo to one healthy Polaris instance."""

    consumer: ConsumerAPI
    service: str
    loop: asyncio.AbstractEventLoop

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path != "/echo":
            self.send_error(404)
            return
        try:
            body = asyncio.run_coroutine_threadsafe(self._forward(), self.loop).result(timeout=10)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            logging.getLogger(__name__).exception("proxy request failed")
            body = json.dumps({"error": str(exc)}).encode()
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        logging.getLogger(__name__).info(format, *args)

    async def _forward(self) -> bytes:
        instance = await self.consumer.async_get_one_instance(self.service)
        return await asyncio.to_thread(
            _fetch,
            f"http://{instance.host}:{instance.port}/echo",
        )


async def main() -> None:
    """Start the local proxy."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="polaris-python-demo")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    context = APIFactory.create_context(Config.from_env())
    consumer = APIFactory.create_consumer_api(context)
    ProxyHandler.consumer = consumer
    ProxyHandler.service = args.service
    ProxyHandler.loop = asyncio.get_running_loop()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ProxyHandler)
    task = asyncio.create_task(asyncio.to_thread(server.serve_forever))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            pass
    logging.info("consumer proxy listening on http://127.0.0.1:%s/echo", args.port)
    try:
        await stop.wait()
    finally:
        server.shutdown()
        await task
        await context.async_destroy()


if __name__ == "__main__":
    asyncio.run(main())
