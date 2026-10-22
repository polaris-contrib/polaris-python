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

"""Discover an existing service, wait for idle expiry, then load it again."""

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import demo_backup_directory, demo_log_options

import argparse
import json
import os
import time

from polaris import Configuration, ConsumerAPI, SDKError, init_context_by_config
from polaris.pkg.model.service import GetInstancesRequest


def run(consumer, namespace, service, idle_seconds):
    """Exercise discovery and reload without reading the cache during the idle period."""
    request = GetInstancesRequest(namespace=namespace, service=service)
    first = consumer.get_instances(request)
    initial_ids = [instance.get_id() for instance in first.get_instances()]
    time.sleep(idle_seconds)
    second = consumer.get_instances(GetInstancesRequest(namespace=namespace, service=service))
    return {"initial_ids": initial_ids,
            "reloaded_ids": [instance.get_id() for instance in second.get_instances()]}


def main():
    """Run a bounded expiry scenario; connecting to a registry requires explicit opt-in."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace")
    parser.add_argument("service")
    parser.add_argument("--config", help="Path to polaris.yaml; otherwise use environment configuration")
    parser.add_argument("--expire-ms", type=int, default=5000)
    args = parser.parse_args()
    if args.expire_ms < 5000:
        parser.error("--expire-ms must be at least 5000")
    if os.environ.get("POLARIS_E2E") != "1":
        print("Set POLARIS_E2E=1 to connect to a registry, or run examples/cache/expiry/verify.py offline.")
        return 0
    context = None
    try:
        config = Configuration.from_file(args.config) if args.config else Configuration.from_env()
        config.set_default()
        config.get_consumer().get_local_cache().service_expire_time = args.expire_ms
        config.get_consumer().get_local_cache().persist_dir = str(
            demo_backup_directory(__file__, component="expiry")
        )
        context = init_context_by_config(
            config,
            log_options=demo_log_options(__file__, component="expiry"),
        )
        check_ms = min(args.expire_ms / 2, 3600000)
        result = run(ConsumerAPI(context), args.namespace, args.service,
                     (args.expire_ms + check_ms) / 1000 + 0.5)
    except SDKError as error:
        parser.exit(1, f"{error.msg}\n")
    finally:
        if context is not None:
            context.destroy()
    result["context_destroyed"] = context.is_destroy()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
