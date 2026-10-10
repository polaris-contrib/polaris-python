"""Call a service through Polaris with server-provided circuit-breaker rules."""

from __future__ import annotations

import argparse
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from polaris_python import Config
from polaris_python.api.factory import APIFactory
from polaris_python.core.error import CircuitOpenError


def _request(url: str) -> tuple[int, bytes]:
    try:
        with urlopen(url, timeout=3) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def main() -> None:
    """Resolve an instance, invoke it, and report failures to the breaker."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="CircuitBreakerCallee")
    parser.add_argument("--path", default="/echo")
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()

    context = APIFactory.create_context(Config.from_env())
    consumer = APIFactory.create_consumer_api(context)
    try:
        for index in range(args.count):
            try:
                instance = consumer.get_one_instance(args.service)
                try:
                    status, body = _request(f"http://{instance.host}:{instance.port}{args.path}")
                except URLError as exc:
                    status, body = 599, str(exc).encode()
                consumer.update_service_call_result(
                    instance,
                    success=200 <= status < 300,
                )
                print(f"{index + 1}: status={status} body={body[:80]!r}")
            except CircuitOpenError as exc:
                print(f"{index + 1}: blocked by Polaris circuit breaker: {exc}")
    finally:
        context.destroy()


if __name__ == "__main__":
    main()
