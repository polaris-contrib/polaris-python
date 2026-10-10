"""Discover one provider with the synchronous ConsumerAPI facade."""

from __future__ import annotations

import argparse
import logging
from urllib.request import urlopen

from polaris_python import Config
from polaris_python.api.consumer import ConsumerAPI
from polaris_python.api.factory import APIFactory


def main() -> None:
    """Discover a healthy instance, call it, and report the call result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="polaris-python-demo")
    parser.add_argument("--path", default="/echo")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    context = APIFactory.create_context(Config.from_env())
    consumer = APIFactory.create_consumer_api(context)
    try:
        # Sync facade: the equivalent async call is used by consumer.py.
        instance = consumer.get_one_instance(args.service)
        with urlopen(f"http://{instance.host}:{instance.port}{args.path}", timeout=3) as response:
            body = response.read()
        print(body.decode("utf-8", errors="replace"), end="")
    finally:
        context.destroy()


if __name__ == "__main__":
    main()
