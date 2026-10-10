"""Call a service through Polaris with server-provided rate-limit rules."""

from __future__ import annotations

import argparse
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from polaris_python import Config
from polaris_python.api.factory import APIFactory


def _request(url: str) -> tuple[int, bytes]:
    try:
        with urlopen(url, timeout=3) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def main() -> None:
    """Resolve one instance per request and show server-side rate limiting."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="RateLimitEchoServer")
    parser.add_argument("--path", default="/echo")
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()

    context = APIFactory.create_context(Config.from_env())
    consumer = APIFactory.create_consumer_api(context)
    try:
        for index in range(args.count):
            instance = consumer.get_one_instance(args.service)
            started = time.perf_counter()
            try:
                status, body = _request(f"http://{instance.host}:{instance.port}{args.path}")
            except URLError as exc:
                status, body = 599, str(exc).encode()
            latency_ms = (time.perf_counter() - started) * 1000
            consumer.update_service_call_result(
                instance,
                success=200 <= status < 300,
                latency_ms=latency_ms,
            )
            print(f"{index + 1}: status={status} latency_ms={latency_ms:.1f} body={body[:80]!r}")
    finally:
        context.destroy()


if __name__ == "__main__":
    main()
