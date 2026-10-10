"""Call a rule-routed service with request headers and query arguments."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from examples.route._common import run_consumer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="RouteEchoServer")
    parser.add_argument("--namespace", default=os.getenv("POLARIS_NAMESPACE", "default"))
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()

    def request_kwargs(_path: str, query: Mapping[str, str], headers: Mapping[str, str]) -> dict[str, object]:
        return {
            "routing_metadata": dict(query),
            "headers": headers,
            "query": query,
            "method": "GET",
        }

    run_consumer(
        service=args.service,
        namespace=args.namespace,
        port=args.port,
        request_kwargs=request_kwargs,
        title="RouteEchoServer Consumer",
    )


if __name__ == "__main__":
    main()
