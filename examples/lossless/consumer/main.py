# Tencent is pleased to support the open source community by making polaris-python available.
#
# Copyright (C) 2021 Tencent. All rights reserved.
#
# Licensed under the BSD 3-Clause License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://opensource.org/licenses/BSD-3-Clause
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Select a lossless provider and print its warmup traffic distribution."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import configure_e2e_event_reporting, demo_backup_directory, demo_log_options

import argparse
import asyncio
import json
import os
import signal
from collections import Counter

from aiohttp import ClientSession

from polaris import Configuration, create_consumer_by_config
from polaris.pkg.model.service import GetOneInstanceRequest


async def run(args, stop=None):
    """Continuously select and invoke one provider instance."""
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    config = Configuration.from_file(str(args.config))
    configure_e2e_event_reporting(config)
    config.get_consumer().get_local_cache().persist_dir = str(
        demo_backup_directory(__file__, component="consumer")
    )
    consumer = create_consumer_by_config(
        config, log_options=demo_log_options(__file__, component="consumer")
    )
    counts = Counter()
    errors = Counter()
    try:
        print(json.dumps({"started": True}), flush=True)
        async with ClientSession() as client:
            while not stop.is_set():
                try:
                    node = await consumer.async_get_one_instance(GetOneInstanceRequest(
                        namespace=args.namespace, service=args.service,
                    ))
                    if node is None:
                        raise RuntimeError("No provider instance")
                    host = f"[{node.get_host()}]" if ":" in node.get_host() else node.get_host()
                    async with client.get(
                        f"http://{host}:{node.get_port()}/echo", timeout=args.timeout,
                    ) as response:
                        await response.read()
                        counts[str(node.get_id())] += 1
                        if response.status != 200:
                            errors[str(response.status)] += 1
                except Exception as error:
                    errors[type(error).__name__] += 1
                    print(json.dumps({"error": str(error)}), flush=True)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=args.interval)
                except TimeoutError:
                    pass
        print(json.dumps({
            "calls": dict(counts), "errors": dict(errors),
        }), flush=True)
    finally:
        consumer.destroy()


def main(argv=None):
    """Parse arguments and run the consumer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--service", default="LosslessEchoServer")
    parser.add_argument("--interval", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=2)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("polaris.yaml"))
    args = parser.parse_args(argv)
    if not args.namespace or not args.service:
        parser.error("--namespace and --service must not be empty")
    if args.interval <= 0 or args.timeout <= 0:
        parser.error("--interval and --timeout must be positive")
    if os.getenv("POLARIS_E2E") != "1":
        print(json.dumps({"skipped": True, "reason": "Set POLARIS_E2E=1 to connect to Polaris"}))
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
