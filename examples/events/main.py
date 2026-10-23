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

"""Subscribe to events emitted by capabilities implemented by this SDK."""

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._internal._runtime import demo_backup_directory, demo_log_options
from polaris import Configuration, ConsumerAPI, SDKEventType, init_context_by_config
from polaris.pkg.model.service import GetInstancesRequest


def run(args):
    """Discover one service and print the resource events emitted by the local cache."""
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = args.server.split(",")
    config.get_global().get_server_connector().token = os.getenv("POLARIS_TOKEN", "")
    config.get_global().get_admin().port = args.metrics_port
    config.get_consumer().get_local_cache().persist_dir = str(demo_backup_directory(__file__))
    context = init_context_by_config(config, log_options=demo_log_options(__file__))
    events = []
    try:
        context.get_event_center().register_listener(
            lambda event: events.append(event.event_name), SDKEventType.INSTANCE)
        consumer = ConsumerAPI(context)
        response = consumer.get_instances(GetInstancesRequest(namespace=args.namespace, service=args.service))
        result = {"events": events, "instances": len(response.instances)}
        print(json.dumps(result), flush=True)
        return result
    finally:
        context.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("POLARIS_SERVER_ADDRESS", "127.0.0.1:8091"))
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--service", default="DiscoverEchoServer")
    parser.add_argument("--metrics-port", type=int, default=0)
    args = parser.parse_args(argv)
    if os.getenv("POLARIS_E2E") != "1":
        print("Set POLARIS_E2E=1 to run the event example.")
        return 0
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
