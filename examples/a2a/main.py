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

"""Register and discover A2A metadata through ordinary SDK APIs."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._internal._runtime import demo_backup_directory, demo_log_options
from polaris import Configuration, ConsumerAPI, ProviderAPI, init_context_by_config
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.pkg.model.server import InstanceRegisterRequest, InstanceDeRegisterRequest
from polaris.pkg.model.service import GetAllInstancesRequest, GetOneInstanceRequest


def run(args):
    """Register an already-running agent endpoint and inspect its card metadata."""
    card = json.loads(Path(args.card).read_text(encoding="utf-8"))
    metadata = {"ai-agent-name": card["name"], "a2a.agent.card": json.dumps(card, ensure_ascii=True),
                "a2a.transport": args.transport, "a2a.path": args.path}
    if any(len(value) > 65535 for value in metadata.values()):
        raise ValueError("A2A metadata value exceeds 65535 characters")
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = args.server.split(",")
    config.get_global().get_server_connector().token = os.getenv("POLARIS_TOKEN", "")
    config.get_global().get_admin().port = 0
    config.get_consumer().get_local_cache().persist_dir = str(demo_backup_directory(__file__))
    context = init_context_by_config(config, log_options=demo_log_options(__file__))
    provider, consumer = ProviderAPI(context), ConsumerAPI(context)
    registered = None
    try:
        registered = provider.register_instance(InstanceRegisterRequest(
            namespace=args.namespace, service=args.service, service_token=args.token,
            host=args.host, port=args.port, protocol="http", ttl=5, metadata=metadata))
        deadline = time.monotonic() + 40
        while True:
            try:
                snapshot = consumer.get_all_instances(
                    GetAllInstancesRequest(namespace=args.namespace, service=args.service))
            except SDKError as error:
                retryable = (error.err_code == ErrorCode.ErrCodeAPITimeoutError
                              or (error.err_code == ErrorCode.ErrCodeServerError
                                  and "not found" in error.msg.lower()))
                if not retryable:
                    raise
                snapshot = None
            if snapshot is not None and snapshot.instances:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Registered A2A instance did not become discoverable")
            time.sleep(0.2)
        node = consumer.get_one_instance(GetOneInstanceRequest(namespace=args.namespace, service=args.service))
        if node is None:
            raise RuntimeError("No available agent instance")
        found = node.get_metadata()
        host = node.get_host()
        authority = f"[{host}]" if ":" in host else host
        result = {"agent": json.loads(found["a2a.agent.card"])["name"],
                  "transport": found["a2a.transport"],
                  "endpoint": f"http://{authority}:{node.get_port()}{found['a2a.path']}",
                  "instances": len(snapshot.instances)}
        print(json.dumps(result), flush=True)
        time.sleep(args.duration)
        return result
    finally:
        try:
            if registered is not None:
                provider.deregister_instance(InstanceDeRegisterRequest(
                    namespace=args.namespace, service=args.service, service_token=args.token,
                    host=args.host, port=args.port, instance_id=registered.instance_id))
        finally:
            context.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("POLARIS_SERVER_ADDRESS", "127.0.0.1:8091"))
    parser.add_argument("--token", default=os.getenv("POLARIS_SERVICE_TOKEN", ""))
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--service", default="demo-agent")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--transport", default="JSONRPC")
    parser.add_argument("--path", default="/a2a")
    parser.add_argument("--card", default=str(Path(__file__).with_name("agent-card.json")))
    parser.add_argument("--duration", type=float, default=6)
    args = parser.parse_args(argv)
    if args.duration < 0:
        parser.error("duration must be nonnegative")
    if os.getenv("POLARIS_E2E") != "1":
        print("Set POLARIS_E2E=1 to register an already-running A2A endpoint.")
        return 0
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
