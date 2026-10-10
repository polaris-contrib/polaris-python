"""Call a metadata-routed service with the synchronous ``get_one_instance`` API."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from examples.route._common import parse_metadata, run_consumer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="RouteMetadataEchoServer")
    parser.add_argument("--namespace", default=os.getenv("POLARIS_NAMESPACE", "default"))
    parser.add_argument("--metadata", default="env=dev", help="default key1=value1&key2=value2")
    parser.add_argument("--port", type=int, default=18090)
    args = parser.parse_args()
    default_metadata = parse_metadata(args.metadata)

    def request_kwargs(_path: str, query: Mapping[str, str], _headers: Mapping[str, str]) -> dict[str, object]:
        metadata = dict(query) or default_metadata
        return {"metadata": metadata, "routing_metadata": metadata}

    run_consumer(
        service=args.service,
        namespace=args.namespace,
        port=args.port,
        request_kwargs=request_kwargs,
        title="RouteMetadataEchoServer Consumer",
    )


if __name__ == "__main__":
    main()
