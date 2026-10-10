"""Call a nearby-routed service using the caller's region, zone and campus."""

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
    parser.add_argument("--service", default="RouteNearbyEchoServer")
    parser.add_argument("--namespace", default=os.getenv("POLARIS_NAMESPACE", "default"))
    parser.add_argument("--region", default=os.getenv("REGION", "china"))
    parser.add_argument("--zone", default=os.getenv("ZONE", "ap-guangzhou"))
    parser.add_argument("--campus", default=os.getenv("CAMPUS", "ap-guangzhou-1"))
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    location = {"region": args.region, "zone": args.zone, "campus": args.campus}

    def request_kwargs(_path: str, _query: Mapping[str, str], _headers: Mapping[str, str]) -> dict[str, object]:
        return {"routing_metadata": location}

    run_consumer(
        service=args.service,
        namespace=args.namespace,
        port=args.port,
        request_kwargs=request_kwargs,
        title="RouteNearbyEchoServer Consumer",
    )


if __name__ == "__main__":
    main()
