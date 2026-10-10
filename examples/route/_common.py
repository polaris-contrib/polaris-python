"""Shared synchronous helpers for the route examples."""

from __future__ import annotations

import logging
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlparse
from urllib.request import Request, urlopen

from polaris_python import Config, ProviderAPI, ServiceInstance
from polaris_python.api.factory import APIFactory


def parse_metadata(value: str) -> dict[str, str]:
    """Parse the Go example's ``key=value&key2=value2`` syntax."""
    return {key: item for key, item in parse_qsl(value, keep_blank_values=True) if key}


def metadata_from_request(path: str) -> dict[str, str]:
    """Use query parameters as route metadata, matching the Go examples."""
    return {key: values[-1] for key, values in _query_values(path).items() if values}


def run_provider(
    *,
    service: str,
    namespace: str,
    host: str,
    port: int,
    metadata: Mapping[str, str],
    region: str = "",
    zone: str = "",
    campus: str = "",
    ttl_seconds: int | None = 10,
    title: str = "RouteEchoServer",
) -> None:
    """Register one HTTP provider and keep its heartbeat alive."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = Config.from_env()
    context = APIFactory.create_context(config)
    provider: ProviderAPI = APIFactory.create_provider_api(context)
    server = ThreadingHTTPServer((host, port), _EchoHandler)
    instance = ServiceInstance(
        service=service,
        namespace=namespace,
        host=host,
        port=server.server_address[1],
        metadata=dict(metadata),
        region=region,
        zone=zone,
        campus=campus,
        protocol="http",
        version="v1",
        ttl_seconds=ttl_seconds,
    )
    _EchoHandler.title = title
    _EchoHandler.host = host
    _EchoHandler.port = instance.port
    _EchoHandler.metadata = dict(metadata)
    _EchoHandler.location = {"region": region, "zone": zone, "campus": campus}
    stop = threading.Event()
    registered = provider.register_instance(instance)
    logging.info(
        "registered %s/%s at %s:%s metadata=%s location=%s",
        registered.namespace,
        registered.service,
        registered.host,
        registered.port,
        registered.metadata,
        _EchoHandler.location,
    )

    def stop_server(signum: int, _frame: object) -> None:
        logging.info("received signal %s", signum)
        stop.set()

    signal.signal(signal.SIGINT, stop_server)
    signal.signal(signal.SIGTERM, stop_server)
    server_thread = threading.Thread(target=server.serve_forever, name="route-http", daemon=True)
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(provider, registered, stop, ttl_seconds),
        name="route-heartbeat",
        daemon=True,
    )
    server_thread.start()
    heartbeat_thread.start()
    logging.info("%s listening on http://%s:%s/echo", title, host, instance.port)
    try:
        stop.wait()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()
        heartbeat_thread.join()
        provider.deregister_instance(registered)
        context.destroy()


def run_consumer(
    *,
    service: str,
    namespace: str,
    port: int,
    request_kwargs: Callable[[str, Mapping[str, str], Mapping[str, str]], dict[str, object]],
    title: str,
) -> None:
    """Expose a synchronous proxy that calls only ``get_one_instance``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    context = APIFactory.create_context(Config.from_env())
    consumer = APIFactory.create_consumer_api(context)
    stop = threading.Event()

    class ConsumerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            parsed = urlparse(self.path)
            if parsed.path != "/echo":
                self.send_error(404)
                return
            query = metadata_from_request(self.path)
            headers = {name.lower(): value for name, value in self.headers.items()}
            try:
                instance = consumer.get_one_instance(
                    service,
                    namespace=namespace,
                    **request_kwargs(self.path, query, headers),
                )
                body, status = _call_instance(instance, parsed.query, self.headers)
                consumer.update_service_call_result(instance, success=200 <= status < 400)
            except Exception as exc:  # SDK examples should return an actionable HTTP error.
                logging.exception("%s failed to select or call an instance", title)
                body = f"{title} failed: {exc}\n".encode()
                status = 503
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            logging.getLogger(__name__).info(format, *args)

    server = ThreadingHTTPServer(("127.0.0.1", port), ConsumerHandler)

    def stop_server(signum: int, _frame: object) -> None:
        logging.info("received signal %s", signum)
        stop.set()

    signal.signal(signal.SIGINT, stop_server)
    signal.signal(signal.SIGTERM, stop_server)
    thread = threading.Thread(target=server.serve_forever, name="route-consumer-http", daemon=True)
    thread.start()
    logging.info("%s listening on http://127.0.0.1:%s/echo", title, server.server_address[1])
    try:
        stop.wait()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        context.destroy()


class _EchoHandler(BaseHTTPRequestHandler):
    """Tiny provider response used by all route demonstrations."""

    title = "RouteEchoServer"
    host = "127.0.0.1"
    port = 0
    metadata: dict[str, str] = {}
    location: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        path = urlparse(self.path).path
        if path not in {"/echo", "/health"}:
            self.send_error(404)
            return
        if path == "/health":
            body = b"ok\n"
        else:
            body = (
                f"Hello, I'm {self.title} Provider, metadata={self.metadata}, "
                f"location={self.location}, host={self.host}:{self.port}\n"
            ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        logging.getLogger(__name__).info(format, *args)


def _heartbeat_loop(provider: ProviderAPI, instance: ServiceInstance, stop: threading.Event, ttl: int | None) -> None:
    interval = max(1.0, min(5.0, (ttl or 10) / 2))
    while not stop.wait(interval):
        provider.heartbeat(instance)


def _call_instance(instance: ServiceInstance, query: str, headers: Mapping[str, str]) -> tuple[bytes, int]:
    request = Request(f"http://{instance.host}:{instance.port}/echo?{query}" if query else f"http://{instance.host}:{instance.port}/echo")
    for name in ("env", "tenant", "version"):
        if name in headers:
            request.add_header(name, headers[name])
    try:
        with urlopen(request, timeout=3) as response:
            return response.read(), response.status
    except HTTPError as exc:
        return exc.read(), exc.code
    except URLError as exc:
        return str(exc).encode(), 502


def _query_values(path: str) -> dict[str, list[str]]:
    return_value: dict[str, list[str]] = {}
    for key, value in parse_qsl(urlparse(path).query, keep_blank_values=True):
        return_value.setdefault(key, []).append(value)
    return return_value
