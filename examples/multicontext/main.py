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

"""Use two isolated SDK contexts and keep the second running after destroying the first."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2])]
from examples._internal._runtime import configure_e2e_event_reporting, demo_backup_directory, demo_log_options

import argparse
import asyncio
import json
import os
import signal
import threading

from examples._internal._runtime import get_local_host
from polaris import Configuration, ConsumerAPI, ProviderAPI, SDKError, init_context_by_config
from polaris.pkg.model.server import InstanceDeRegisterRequest, InstanceRegisterRequest
from polaris.pkg.model.service import GetInstancesRequest


def create_client(name, address, token, work_dir, level):
    """Assign configuration directly and give this client its own cache and log directory."""
    config = Configuration()
    config.set_default()
    configure_e2e_event_reporting(config)
    config.get_global().get_server_connector().addresses = [address]
    config.get_global().get_server_connector().token = token
    config.get_global().get_api().bind_ip = "127.0.0.1"
    config.get_global().get_stat_reporter().enable = False
    config.get_consumer().get_local_cache().persist_dir = str(work_dir / name)
    return init_context_by_config(config, log_options=demo_log_options(__file__, level=level, component=name))


async def discover(consumer, namespace, service):
    """Fetch a nonempty service snapshot within a bounded timeout."""
    result = await asyncio.wait_for(consumer.async_get_instances(GetInstancesRequest(
        namespace=namespace, service=service, timeout=5000, use_discover_cache=False)), timeout=6)
    nodes = result.get_instances()
    if not nodes:
        raise RuntimeError(f"No instances found for {namespace}/{service}")
    return [{"id": node.get_id(), "host": node.get_host(), "port": node.get_port()} for node in nodes]


def sync_discover(consumer, namespace, service):
    """Run the synchronous discovery API outside the active asyncio loop."""
    result = consumer.get_instances(GetInstancesRequest(
        namespace=namespace, service=service, timeout=5000, use_discover_cache=False,
    ))
    return [{"id": node.get_id(), "host": node.get_host(), "port": node.get_port()}
            for node in result.get_instances()]


async def run(args):
    """Register with both clients, destroy one, and continue discovery with the other."""
    clients = []
    registered = {}
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        for name, address, level in (("first", args.first_server, "debug"), ("second", args.second_server, "error")):
            client = create_client(name, address, os.getenv(f"POLARIS_{name.upper()}_TOKEN", ""),
                                   args.work_dir, level)
            clients.append(client)
            host = get_local_host(client.get_config().get_global().get_server_connector().get_addresses()[0])
            request = InstanceRegisterRequest(args.service, os.getenv(f"POLARIS_{name.upper()}_SERVICE_TOKEN", ""),
                                               args.namespace, host, 8080 + len(clients), ttl=args.ttl)
            response = await ProviderAPI(client).async_register_instance(request)
            registered[client] = InstanceDeRegisterRequest(
                request.service, request.service_token, request.namespace, request.host, request.port,
                response.instance_id)

        first, second = clients
        await asyncio.sleep(args.seconds)
        initial = await asyncio.gather(*(discover(ConsumerAPI(client), args.namespace, args.service) for client in clients))
        initial_sync = await asyncio.gather(*(asyncio.to_thread(
            sync_discover, ConsumerAPI(client), args.namespace, args.service,
        ) for client in clients))
        assert initial_sync == initial, (initial_sync, initial)
        await ProviderAPI(first).async_deregister(registered.pop(first))
        first.destroy()
        rejected = False
        try:
            ConsumerAPI(first).check_available()
        except SDKError:
            rejected = True
        await asyncio.sleep(args.seconds)
        continued = await discover(ConsumerAPI(second), args.namespace, args.service)
        result = {"client_ids": [client.get_client_id() for client in clients],
                  "initial_instances": initial, "second_instances_after_first_destroy": continued,
                  "sync_instances_match_async": True,
                  "first_destroyed": first.is_destroy(), "first_api_rejected": rejected,
                  "second_available_after_first_destroy": not second.is_destroy()}
        print(json.dumps(result, sort_keys=True), flush=True)
        if args.keep_running:
            await asyncio.to_thread(stop.wait)
    finally:
        cleanup_error = None
        for client in reversed(clients):
            try:
                if not client.is_destroy() and client in registered:
                    await ProviderAPI(client).async_deregister(registered[client])
            except SDKError as error:
                cleanup_error = cleanup_error or error
            finally:
                client.destroy()
        if cleanup_error is not None:
            raise cleanup_error
    result["all_destroyed"] = all(client.is_destroy() for client in clients)
    return result


def main() -> int:
    """Run only with explicit E2E opt-in; the verifier supplies fake RPCs offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--service", default="multicontext-example")
    parser.add_argument("--first-server", default=os.getenv("POLARIS_FIRST_SERVER", "127.0.0.1:8091"))
    parser.add_argument("--second-server", default=os.getenv("POLARIS_SECOND_SERVER", "127.0.0.1:8091"))
    parser.add_argument("--ttl", type=int, default=5)
    parser.add_argument("--seconds", type=float, default=6)
    parser.add_argument("--work-dir", "--backup-dir", dest="work_dir", type=Path,
                        default=demo_backup_directory(__file__))
    parser.add_argument("--keep-running", action="store_true",
                        help="keep both registered instances alive until SIGTERM/SIGINT")
    args = parser.parse_args()
    if args.ttl <= 0 or args.seconds <= args.ttl:
        parser.error("--ttl must be positive and --seconds must exceed --ttl")
    if os.getenv("POLARIS_E2E") != "1":
        print(json.dumps({"skipped": True, "reason": "Set POLARIS_E2E=1 to connect to the configured registries"}))
        return 0
    try:
        asyncio.run(run(args))
        return 0
    except (SDKError, OSError, RuntimeError, TimeoutError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
