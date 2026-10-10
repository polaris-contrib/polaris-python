"""Register a provider with region, zone and campus location information."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from examples.route._common import parse_metadata, run_provider


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="RouteNearbyEchoServer")
    parser.add_argument("--namespace", default=os.getenv("POLARIS_NAMESPACE", "default"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--metadata", default="", help="additional key1=value1&key2=value2")
    parser.add_argument("--region", default=os.getenv("REGION", "china"))
    parser.add_argument("--zone", default=os.getenv("ZONE", "ap-guangzhou"))
    parser.add_argument("--campus", default=os.getenv("CAMPUS", "ap-guangzhou-1"))
    args = parser.parse_args()
    run_provider(
        service=args.service,
        namespace=args.namespace,
        host=args.host,
        port=args.port,
        metadata=parse_metadata(args.metadata),
        region=args.region,
        zone=args.zone,
        campus=args.campus,
        ttl_seconds=1,
        title="RouteNearbyEchoServer",
    )


if __name__ == "__main__":
    main()
