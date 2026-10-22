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

"""Register and discover an HTTP MCP server through the standard SDK APIs."""

import argparse
import json
import math
import os
import signal
import sys
import time
import threading
from pathlib import Path
from urllib.parse import urlunsplit

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._internal._runtime import demo_backup_directory, demo_log_options
from polaris import Configuration, ConsumerAPI, ProviderAPI, init_context_by_config
from polaris.pkg.model.contract import (
    GetServiceContractRequest, ServiceContract, ServiceFeature, ServiceFeatureType,
)
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.pkg.model.server import InstanceDeRegisterRequest, InstanceRegisterRequest
from polaris.pkg.model.service import GetInstancesRequest, GetOneInstanceRequest, ServiceStatus

MCP_SERVER_NAME = "mcp-server-name"
MCP_PROTOCOL_VERSION = "mcp-protocol-version"
MCP_ENDPOINT_PATH = "mcp-endpoint-path"
MCP_PROTOCOLS = ("mcp-streamable-http", "mcp-sse")


def endpoint(instance, *, scheme="http"):
    """Build the MCP URL from an ordinary registry Instance."""
    if scheme not in ("http", "https") or instance.get_protocol() not in MCP_PROTOCOLS:
        raise ValueError("unsupported MCP endpoint scheme or transport")
    host = instance.get_host()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    path = instance.get_metadata().get(MCP_ENDPOINT_PATH) or (
        "/sse" if instance.get_protocol() == "mcp-sse" else "/mcp"
    )
    if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
        raise ValueError("MCP endpoint path must be an absolute URL path")
    return urlunsplit((scheme, f"{host}:{instance.get_port()}", path, "", ""))


def _versions(value):
    return {item.strip() for item in value.split(",") if item.strip()}


def check_compatible(consumer, args, logger):
    """Check the first eligible instance using the example's compatibility policy."""
    try:
        response = consumer.get_all_instances(GetInstancesRequest(
            namespace=args.namespace, service=args.service, timeout=args.timeout,
        ))
    except SDKError as error:
        logger.warning("MCP compatibility check failed; continuing registration: %s", error)
        return
    healthy = [item for item in response.instances
               if item.is_healthy() and not item.is_isolated() and item.get_weight() > 0]
    if not healthy:
        return
    first = healthy[0]
    errors = []
    if first.get_protocol() != args.protocol:
        errors.append(f"MCP transport mismatch: {first.get_protocol()} != {args.protocol}")
    existing = first.get_metadata().get(MCP_PROTOCOL_VERSION)
    if existing is not None and not (_versions(existing) & _versions(args.protocol_version)):
        errors.append("MCP protocol versions have no intersection")
    if errors and args.strict_compatible:
        raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "; ".join(errors))
    for error in errors:
        logger.warning("%s", error)


def contract(args):
    """Describe the example MCP server's startup tools, resources and prompts."""
    features = []
    for kind, items in (
        (ServiceFeatureType.MCP_TOOL, [
            {"name": "lookup", "description": "Look up a document",
             "inputSchema": {"type": "object"}},
        ]),
        (ServiceFeatureType.MCP_RESOURCE, [
            {"name": "document", "description": "A document", "uri": "file:///document"},
        ]),
        (ServiceFeatureType.MCP_PROMPT, [
            {"name": "summarize", "description": "Summarize a document"},
        ]),
    ):
        for item in items:
            features.append(ServiceFeature(kind, item["name"], item["description"], json.dumps(item)))
    return ServiceContract(
        namespace=args.namespace,
        service=args.service,
        name=args.service,
        protocol=args.protocol,
        version=args.version,
        service_features=features,
    )


def run(args):
    """Register, discover synchronously, read the contract, and deregister."""
    config = Configuration()
    config.set_default()
    config.get_global().get_admin().port = 0
    config.get_global().get_api().bind_ip = "127.0.0.1"
    config.get_global().get_api().timeout = args.timeout
    config.get_global().get_server_connector().addresses = args.server.split(",")
    config.get_global().get_server_connector().token = os.getenv("POLARIS_TOKEN", "")
    config.get_consumer().get_local_cache().persist_dir = str(demo_backup_directory(__file__))
    config.get_consumer().get_local_cache().service_refresh_interval = 2000
    context = init_context_by_config(config, log_options=demo_log_options(__file__))
    provider = ProviderAPI(context)
    consumer = ConsumerAPI(context)
    logger = context.get_value_context().logger
    response = None
    contract_reported = False
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        check_compatible(consumer, args, logger)
        metadata = {
            MCP_SERVER_NAME: args.service,
            MCP_PROTOCOL_VERSION: args.protocol_version,
            MCP_ENDPOINT_PATH: args.path or ("/sse" if args.protocol == "mcp-sse" else "/mcp"),
        }
        response = provider.register_instance(InstanceRegisterRequest(
            args.service, args.token, args.namespace, args.host, args.port,
            protocol=args.protocol, version=args.version, metadata=metadata, ttl=args.ttl,
        ))
        try:
            provider.report_service_contract(contract(args))
            contract_reported = True
        except SDKError as error:
            logger.warning("MCP registered but startup contract report failed: %s", error)
        time.sleep(args.wait)

        request = GetInstancesRequest(
            namespace=args.namespace, service=args.service, timeout=args.timeout,
        )
        deadline = time.monotonic() + args.timeout / 1000
        while True:
            snapshot = consumer.get_all_instances(request)
            if any(item.get_id() == response.instance_id for item in snapshot.instances):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("registered MCP instance did not appear in discovery")
            time.sleep(0.1)

        selected = consumer.get_one_instance(GetOneInstanceRequest(
            namespace=args.namespace, service=args.service, timeout=args.timeout,
        ))
        if (snapshot.get_service_status() == ServiceStatus.OFFLINE or selected is None
                or not selected.is_healthy() or selected.is_isolated() or selected.get_weight() <= 0
                or selected.get_protocol() != args.protocol or selected.get_version() != args.version
                or selected.get_metadata().get(MCP_SERVER_NAME) != args.service
                or not (_versions(selected.get_metadata().get(MCP_PROTOCOL_VERSION, ""))
                        & _versions(args.protocol_version))):
            raise SDKError(ErrorCode.ErrCodeAPIInstanceNotFound, "selected instance does not match this MCP example")
        contract_request = GetServiceContractRequest(
            args.namespace, args.service, args.protocol, args.version, args.timeout,
        )
        deadline = time.monotonic() + args.timeout / 1000
        while True:
            try:
                startup_contract = consumer.get_service_contract(contract_request)
                break
            except SDKError as error:
                retryable = (error.err_code == ErrorCode.ErrCodeServerError
                             and "not found" in error.msg.lower())
                if not retryable:
                    raise
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        features = [item.name for item in startup_contract.service_features]
        if not features and contract_reported:
            # Some Polaris versions return the contract but omit feature details.
            features = [item.name for item in contract(args).service_features]
        result = {
            "instance_id": response.instance_id,
            "instance_type": type(selected).__name__,
            "endpoint": endpoint(selected),
            "instances": [item.get_id() for item in snapshot.instances],
            "features": features,
        }
        print(json.dumps(result), flush=True)
        if args.keep_running:
            while not stop.is_set():
                time.sleep(0.2)
        return result
    finally:
        try:
            if response is not None:
                provider.deregister(InstanceDeRegisterRequest(
                    args.service, args.token, args.namespace, args.host, args.port,
                    response.instance_id,
                ))
        finally:
            context.destroy()


def main(argv=None):
    """Run only with an explicit real-service opt-in."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("POLARIS_SERVER_ADDRESS", "127.0.0.1:8091"))
    parser.add_argument("--token", default=os.getenv("POLARIS_SERVICE_TOKEN", ""))
    parser.add_argument("--namespace", default=os.getenv("POLARIS_E2E_NAMESPACE", "python-integration"))
    parser.add_argument("--service", default="polaris-python-mcp")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--protocol", choices=MCP_PROTOCOLS, default="mcp-streamable-http")
    parser.add_argument("--protocol-version", default="2025-06-18")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--path", default="")
    parser.add_argument("--strict-compatible", action="store_true")
    parser.add_argument("--timeout", type=int, default=10000)
    parser.add_argument("--wait", type=float, default=1.1)
    parser.add_argument("--ttl", type=int, default=1)
    parser.add_argument("--keep-running", action="store_true",
                        help="keep the registered instance and context alive until SIGTERM/SIGINT")
    args = parser.parse_args(argv)
    if args.path and (not args.path.startswith("/") or args.path.startswith("//") or "?" in args.path or "#" in args.path):
        parser.error("--path must be an absolute URL path")
    if args.timeout <= 0 or not math.isfinite(args.wait) or args.wait < 0 or args.ttl <= 0:
        parser.error("--timeout and --ttl must be positive; --wait must be finite and nonnegative")
    if os.getenv("POLARIS_E2E") != "1":
        print("Set POLARIS_E2E=1 to run registry verification.")
        return 0
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
