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
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Discover a service using a reusable disk backup directory."""

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import demo_backup_directory, demo_log_options

import argparse
import asyncio
import json
import os

from polaris import Configuration, ConsumerAPI, SDKError, init_context_by_config
from polaris.pkg.model.service import GetInstancesRequest


def describe(result):
    """Describe the discovered instances and persisted resource revisions."""
    return {
        "ids": [instance.get_id() for instance in result.get_instances()],
        "hosts": [instance.get_host() for instance in result.get_instances()],
        "instance_revision": result.get_revision(),
    }


async def run(consumer, namespace, service):
    """Use the public asynchronous discovery API."""
    return describe(await consumer.async_get_instances(GetInstancesRequest(namespace=namespace, service=service)))


def main():
    """Run against a registry only after explicit opt-in, leaving backups on exit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace")
    parser.add_argument("service")
    parser.add_argument("--config", help="Path to polaris.yaml")
    parser.add_argument("--metrics-port", type=int, default=None)
    parser.add_argument("--persist-dir", type=Path,
                        default=demo_backup_directory(__file__, component="restart"))
    args = parser.parse_args()
    if os.environ.get("POLARIS_E2E") != "1":
        print("Set POLARIS_E2E=1 to connect to a registry, or run examples/cache/restart/verify.py locally.")
        return 0
    config = Configuration.from_file(args.config) if args.config else Configuration.from_env()
    config.set_default()
    if args.metrics_port is not None:
        config.get_global().get_admin().port = args.metrics_port
    config.get_consumer().get_local_cache().persist_dir = str(args.persist_dir)
    context = init_context_by_config(
        config,
        log_options=demo_log_options(__file__, component="restart"),
    )
    try:
        print(json.dumps(asyncio.run(run(ConsumerAPI(context), args.namespace, args.service))))
    except SDKError as error:
        parser.exit(1, f"{error}\n")
    finally:
        context.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
