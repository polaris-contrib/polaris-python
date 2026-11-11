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

"""Register an HTTP MCP server through ordinary Polaris instance APIs."""

import argparse
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlunsplit

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._support import demo_backup_directory, demo_log_options, get_local_host
from polaris import Configuration, ConsumerAPI, ProviderAPI, init_context_by_config
from polaris.pkg.model.contract import (
    GetServiceContractRequest,
    ServiceContract,
    ServiceFeature,
    ServiceFeatureType,
)
from polaris.pkg.model.server import InstanceDeRegisterRequest, InstanceRegisterRequest
from polaris.pkg.model.service import GetInstancesRequest


MCP_PROTOCOLS = ("mcp-streamable-http", "mcp-sse")


def mcp_endpoint(instance):
    host = instance.get_host()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    path = instance.get_metadata().get("mcp-endpoint-path") or (
        "/sse" if instance.get_protocol() == "mcp-sse" else "/mcp"
    )
    return urlunsplit(("http", f"{host}:{instance.get_port()}", path, "", ""))


def mcp_contract(args):
    features = [
        ServiceFeature(
            ServiceFeatureType.MCP_TOOL,
            "lookup",
            "Look up a document",
            json.dumps({"name": "lookup", "inputSchema": {"type": "object"}}),
        ),
        ServiceFeature(
            ServiceFeatureType.MCP_RESOURCE,
            "document",
            "A document",
            json.dumps({"name": "document", "uri": "file:///document"}),
        ),
        ServiceFeature(
            ServiceFeatureType.MCP_PROMPT,
            "summarize",
            "Summarize a document",
            json.dumps({"name": "summarize"}),
        ),
    ]
    return ServiceContract(
        namespace=args.namespace,
        service=args.service,
        name=args.service,
        protocol=args.protocol,
        version=args.version,
        service_features=features,
    )


def wait_for_instance(consumer, args, instance_id):
    deadline = time.monotonic() + args.timeout / 1000
    request = GetInstancesRequest(
        namespace=args.namespace,
        service=args.service,
        timeout=args.timeout,
    )
    while time.monotonic() < deadline:
        snapshot = consumer.get_all_instances(request)
        selected = next(
            (item for item in snapshot.instances if item.get_id() == instance_id),
            None,
        )
        if selected is not None:
            return snapshot, selected
        time.sleep(0.2)
    raise RuntimeError("registered MCP instance did not become discoverable")


def run(args):
    if not args.host:
        args.host = get_local_host(args.server.split(",", 1)[0].strip())
    config = Configuration()
    config.set_default()
    config.get_global().get_admin().port = 0
    config.get_global().get_api().bind_ip = "127.0.0.1"
    config.get_global().get_api().timeout = args.timeout
    config.get_global().get_server_connector().addresses = args.server.split(",")
    config.get_global().get_server_connector().token = os.getenv("POLARIS_TOKEN", "")
    config.get_consumer().get_local_cache().persist_dir = str(
        demo_backup_directory(__file__)
    )
    context = init_context_by_config(
        config,
        log_options=demo_log_options(__file__),
    )
    provider, consumer = ProviderAPI(context), ConsumerAPI(context)
    registered = None
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        registered = provider.register_instance(InstanceRegisterRequest(
            service=args.service,
            service_token=args.token,
            namespace=args.namespace,
            host=args.host,
            port=args.port,
            protocol=args.protocol,
            version=args.version,
            ttl=args.ttl,
            metadata={
                "mcp-server-name": args.service,
                "mcp-protocol-version": args.protocol_version,
                "mcp-endpoint-path": args.path or (
                    "/sse" if args.protocol == "mcp-sse" else "/mcp"
                ),
            },
        ))
        provider.report_service_contract(mcp_contract(args))
        snapshot, selected = wait_for_instance(consumer, args, registered.instance_id)
        contract = consumer.get_service_contract(GetServiceContractRequest(
            args.namespace,
            args.service,
            args.protocol,
            args.version,
            args.timeout,
        ))
        print(json.dumps({
            "instance_id": registered.instance_id,
            "instance_type": type(selected).__name__,
            "endpoint": mcp_endpoint(selected),
            "instances": [item.get_id() for item in snapshot.instances],
            "features": [item.name for item in contract.service_features],
            "host": selected.get_host(),
            "port": selected.get_port(),
        }), flush=True)
        if args.keep_running:
            while not stop.wait(0.2):
                pass
    finally:
        try:
            if registered is not None:
                provider.deregister(InstanceDeRegisterRequest(
                    args.service,
                    args.token,
                    args.namespace,
                    args.host,
                    args.port,
                    registered.instance_id,
                ))
        finally:
            context.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("POLARIS_SERVER_ADDRESS", "127.0.0.1:8091"))
    parser.add_argument("--token", default=os.getenv("POLARIS_SERVICE_TOKEN", ""))
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--service", default="polaris-python-mcp")
    parser.add_argument("--host", help="advertised host; defaults to the Polaris route source IP")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--protocol", choices=MCP_PROTOCOLS, default="mcp-streamable-http")
    parser.add_argument("--protocol-version", default="2025-06-18")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--path", default="")
    parser.add_argument("--timeout", type=int, default=10000)
    parser.add_argument("--ttl", type=int, default=1)
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.ttl <= 0:
        parser.error("--timeout and --ttl must be positive")
    if args.path and (
        not args.path.startswith("/")
        or args.path.startswith("//")
        or "?" in args.path
        or "#" in args.path
    ):
        parser.error("--path must be an absolute URL path")
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
