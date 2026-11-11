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

"""Register one A2A AgentCard as ordinary Polaris instance metadata."""

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._support import demo_backup_directory, demo_log_options
from polaris import Configuration, ConsumerAPI, ProviderAPI, init_context_by_config
from polaris.pkg.model.server import InstanceDeRegisterRequest, InstanceRegisterRequest
from polaris.pkg.model.service import GetAllInstancesRequest


@contextmanager
def stop_on_signals(loop, stop):
    previous = {}

    def request_stop(_signum, _frame):
        loop.call_soon_threadsafe(stop.set)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, request_stop)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def first_interface(card, a2a_version):
    """Read the first advertised interface from a 0.3 or 1.0 AgentCard."""
    if a2a_version == "1.0":
        item = card["supportedInterfaces"][0]
        return item["url"], item["protocolBinding"]
    return card["url"], card.get("preferredTransport", "JSONRPC")


async def wait_for_registration(consumer, namespace, service, instance_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        snapshot = await consumer.async_get_all_instances(
            GetAllInstancesRequest(namespace=namespace, service=service),
        )
        node = next(
            (item for item in snapshot.instances if item.get_id() == instance_id),
            None,
        )
        if node is not None:
            return snapshot, node
        await asyncio.sleep(0.2)
    raise RuntimeError(f"instance {instance_id} did not become discoverable")


async def run(args):
    card_text = Path(args.card).read_text(encoding="utf-8")
    card = json.loads(card_text)
    endpoint, transport = first_interface(card, args.a2a_version)
    host = urlsplit(endpoint).hostname
    if not host:
        raise ValueError("AgentCard interface URL must contain a host")

    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = args.server.split(",")
    config.get_global().get_server_connector().token = os.getenv("POLARIS_TOKEN", "")
    config.get_global().get_admin().port = 0
    config.get_consumer().get_local_cache().persist_dir = str(
        demo_backup_directory(__file__)
    )
    context = await asyncio.to_thread(
        init_context_by_config,
        config,
        log_options=demo_log_options(__file__),
    )
    provider, consumer = ProviderAPI(context), ConsumerAPI(context)
    registered = None
    stop = asyncio.Event()
    try:
        with stop_on_signals(asyncio.get_running_loop(), stop):
            registered = await provider.async_register_instance(InstanceRegisterRequest(
                namespace=args.namespace,
                service=card["name"],
                service_token=args.token,
                host=host,
                port=args.registration_port,
                protocol="",
                version=card["version"],
                ttl=5,
                metadata={
                    "ai-agent-name": card["name"],
                    "ai-agent-card": card_text,
                    "ai-a2a-version": args.a2a_version,
                },
            ))
            snapshot, node = await wait_for_registration(
                consumer,
                args.namespace,
                card["name"],
                registered.instance_id,
            )
            print(json.dumps({
                "agent": node.get_metadata()["ai-agent-name"],
                "a2a_version": node.get_metadata()["ai-a2a-version"],
                "version": node.get_version(),
                "transport": transport,
                "endpoint": endpoint,
                "instances": len(snapshot.instances),
                "instance_id": registered.instance_id,
            }), flush=True)
            if args.keep_running:
                await stop.wait()
            else:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=args.duration)
                except TimeoutError:
                    pass
    finally:
        if registered is not None:
            await provider.async_deregister_instance(InstanceDeRegisterRequest(
                namespace=args.namespace,
                service=card["name"],
                service_token=args.token,
                host=host,
                port=args.registration_port,
                instance_id=registered.instance_id,
            ))
        await asyncio.to_thread(context.destroy)


def registration_port(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("registration port must be in range 1..65535")
    return port


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("POLARIS_SERVER_ADDRESS", "127.0.0.1:8091"))
    parser.add_argument("--token", default=os.getenv("POLARIS_SERVICE_TOKEN", ""))
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--card", default=str(Path(__file__).with_name("agent-card.json")))
    parser.add_argument("--a2a-version", choices=("0.3", "1.0"), default="1.0")
    parser.add_argument("--registration-port", type=registration_port, default=1)
    parser.add_argument("--duration", type=float, default=6)
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args(argv)
    if args.duration < 0:
        parser.error("duration must be nonnegative")
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
