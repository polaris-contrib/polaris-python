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
import asyncio
import ipaddress
import json
import os
import signal
import sys
import time
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from integration._support import (
    configure_e2e_event_reporting,
    demo_backup_directory,
    demo_log_options,
)
from polaris import Configuration, ConsumerAPI, ProviderAPI, init_context_by_config
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.pkg.model.server import InstanceRegisterRequest, InstanceDeRegisterRequest
from polaris.pkg.model.service import GetAllInstancesRequest


SUPPORTED_A2A_VERSIONS = ("0.3", "1.0")
AGENT_METADATA_KEYS = {"ai-agent-name", "ai-agent-card", "ai-a2a-version"}
SERVER_METADATA_KEYS = {"region", "zone", "campus", "version"}
LEGACY_SCHEMA_FIELDS = {"protocolVersion", "url", "preferredTransport", "additionalInterfaces"}


def _require_text(value, field, *, reject_outer_whitespace=False):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if reject_outer_whitespace and value != value.strip():
        raise ValueError(f"{field} must not have leading or trailing whitespace")
    return value


def _reject_mixed_schema(card, a2a_version):
    if a2a_version == "1.0":
        legacy_fields = sorted(LEGACY_SCHEMA_FIELDS.intersection(card))
        if legacy_fields:
            raise ValueError(
                "A2A 1.0 AgentCard must not contain 0.3 schema fields: "
                + ", ".join(legacy_fields))
    elif a2a_version == "0.3" and "supportedInterfaces" in card:
        raise ValueError(
            "A2A 0.3 AgentCard must not contain the 1.0 field supportedInterfaces")


def _card_interfaces(card, a2a_version):
    if not isinstance(card, dict):
        raise ValueError("AgentCard must be a JSON object")
    if a2a_version == "1.0":
        raw_interfaces = card.get("supportedInterfaces")
        if not isinstance(raw_interfaces, list) or not raw_interfaces:
            raise ValueError("A2A 1.0 AgentCard must define supportedInterfaces")
        interfaces = []
        for index, item in enumerate(raw_interfaces):
            if not isinstance(item, dict):
                raise ValueError(f"supportedInterfaces[{index}] must be a JSON object")
            interfaces.append({
                "url": _require_text(
                    item.get("url"), f"supportedInterfaces[{index}].url",
                    reject_outer_whitespace=True),
                "transport": _require_text(
                    item.get("protocolBinding"),
                    f"supportedInterfaces[{index}].protocolBinding",
                    reject_outer_whitespace=True),
            })
        return interfaces
    if a2a_version == "0.3":
        protocol_version = card.get("protocolVersion")
        if protocol_version not in ("0.3", "0.3.0"):
            raise ValueError("A2A 0.3 AgentCard protocolVersion must be 0.3 or 0.3.0")
        preferred_transport = card.get("preferredTransport")
        if preferred_transport is None:
            preferred_transport = "JSONRPC"
        interfaces = [{
            "url": _require_text(
                card.get("url"), "AgentCard.url", reject_outer_whitespace=True),
            "transport": _require_text(
                preferred_transport, "AgentCard.preferredTransport",
                reject_outer_whitespace=True),
        }]
        additional = card.get("additionalInterfaces")
        if additional is None:
            additional = []
        if not isinstance(additional, list):
            raise ValueError("additionalInterfaces must be a JSON array")
        for index, item in enumerate(additional):
            if not isinstance(item, dict):
                raise ValueError(f"additionalInterfaces[{index}] must be a JSON object")
            interfaces.append({
                "url": _require_text(
                    item.get("url"), f"additionalInterfaces[{index}].url",
                    reject_outer_whitespace=True),
                "transport": _require_text(
                    item.get("transport"), f"additionalInterfaces[{index}].transport",
                    reject_outer_whitespace=True),
            })
        return interfaces
    raise ValueError(f"unsupported AgentCard schema version: {a2a_version!r}")


def _interface_ip(url):
    """Return the normalized literal IP embedded in one AgentCard interface URL."""
    value = _require_text(
        url, "AgentCard interface URL", reject_outer_whitespace=True)
    if any(ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value):
        raise ValueError("AgentCard interface URL must not contain control characters")
    candidate = value if "://" in value else "//" + value
    parsed = urlsplit(candidate)
    if not parsed.netloc or parsed.hostname is None or parsed.username or parsed.password:
        raise ValueError(f"AgentCard interface URL {value!r} must contain an IP authority")
    try:
        address = ipaddress.ip_address(parsed.hostname)
        port = parsed.port
    except ValueError as error:
        raise ValueError(
            f"AgentCard interface URL {value!r} must use a concrete IP and valid port") from error
    if port is None or not 1 <= port <= 65535:
        raise ValueError(f"AgentCard interface URL {value!r} must use a port in range 1..65535")
    return str(address)


def parse_agent_card(card, a2a_version):
    """Validate one instance-level AgentCard and derive its registration identity."""
    if not isinstance(card, dict):
        raise ValueError("AgentCard must be a JSON object")
    _reject_mixed_schema(card, a2a_version)
    name = _require_text(card.get("name"), "AgentCard.name")
    version = _require_text(card.get("version"), "AgentCard.version")
    interfaces = _card_interfaces(card, a2a_version)
    hosts = {_interface_ip(interface["url"]) for interface in interfaces}
    if len(hosts) != 1:
        raise ValueError(
            "AgentCard interfaces must all use the same IP; found: " + ", ".join(sorted(hosts)))
    return {"name": name, "version": version, "host": hosts.pop(), "interfaces": interfaces}


def find_registered_instance(instances, instance_id):
    """Return the instance created by the current registration, never a load-balanced peer."""
    return next((instance for instance in instances if instance.get_id() == instance_id), None)


def validate_registered_instance(node, card_text, a2a_version, registration_port):
    """Return the parsed card when discovery reflects the current registration."""
    found = node.get_metadata()
    if not isinstance(found, Mapping):
        raise ValueError("registered instance metadata is not an object")
    missing = AGENT_METADATA_KEYS - set(found)
    if missing:
        raise ValueError(f"missing A2A metadata keys: {sorted(missing)}")
    unexpected = set(found) - AGENT_METADATA_KEYS - SERVER_METADATA_KEYS
    if unexpected:
        raise ValueError(f"unexpected A2A metadata keys: {sorted(unexpected)}")
    if found["ai-agent-card"] != card_text:
        raise ValueError("registered AgentCard differs from the input JSON")
    if found["ai-a2a-version"] != a2a_version:
        raise ValueError("registered a2a version differs from the selected schema")
    found_registration = parse_agent_card(
        json.loads(found["ai-agent-card"]), found["ai-a2a-version"])
    if found["ai-agent-name"] != found_registration["name"]:
        raise ValueError("ai-agent-name does not match AgentCard.name")
    if node.get_host() != found_registration["host"]:
        raise ValueError("instance host does not match the AgentCard interface IP")
    if node.get_port() != registration_port:
        raise ValueError("instance port does not match registration_port")
    if node.get_version() != found_registration["version"]:
        raise ValueError("instance version does not match AgentCard.version")
    if node.get_protocol() != "":
        raise ValueError("A2A instance protocol must be empty")
    return found_registration


def _restore_signal_handlers(previous):
    for signum, handler in previous.items():
        signal.signal(signum, handler)


@contextmanager
def capture_stop_signals(loop, stop):
    """Capture stop signals for the complete A2A process lifecycle."""
    previous = {}

    def request_stop(_signum, _frame):
        loop.call_soon_threadsafe(stop.set)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, request_stop)
    except BaseException:
        _restore_signal_handlers(previous)
        raise
    try:
        yield
    finally:
        _restore_signal_handlers(previous)


_STOPPED = object()


async def _wait_for_stop(stop, timeout):
    """Wait for a stop request, returning True if it arrives before the timeout."""
    if timeout <= 0 or stop.is_set():
        return stop.is_set()
    try:
        await asyncio.wait_for(stop.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        return False
    return True


async def _wait_for_completion_or_stop(stop, operation):
    """Cancel an in-flight operation as soon as stop is requested."""
    if stop.is_set():
        if asyncio.iscoroutine(operation):
            operation.close()
        return _STOPPED
    operation_task = asyncio.create_task(operation)
    stop_task = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait(
            (operation_task, stop_task), return_when=asyncio.FIRST_COMPLETED)
        if operation_task in done:
            return operation_task.result()
        operation_task.cancel()
        await asyncio.gather(operation_task, return_exceptions=True)
        return _STOPPED
    finally:
        if not stop_task.done():
            stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        if not operation_task.done():
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)


def run(args):
    """Register an already-running agent endpoint and inspect its card metadata."""
    return asyncio.run(_run_with_signals(args))


async def _run_with_signals(args):
    stop = asyncio.Event()
    with capture_stop_signals(asyncio.get_running_loop(), stop):
        return await _run(args, stop)


async def _run(args, stop):
    """Run the A2A fixture with an externally managed stop event."""
    card_text = Path(args.card).read_text(encoding="utf-8")
    registration = parse_agent_card(json.loads(card_text), args.a2a_version)
    if stop.is_set():
        return {"stopped": True}
    metadata = {
        "ai-agent-name": registration["name"],
        "ai-agent-card": card_text,
        "ai-a2a-version": args.a2a_version,
    }
    if any(len(value.encode("utf-8")) > 65535 for value in metadata.values()):
        raise ValueError("A2A metadata value exceeds 65535 UTF-8 bytes")
    config = Configuration()
    config.set_default()
    configure_e2e_event_reporting(config)
    config.get_global().get_server_connector().addresses = args.server.split(",")
    config.get_global().get_server_connector().token = os.getenv("POLARIS_TOKEN", "")
    config.get_global().get_admin().port = 0
    config.get_consumer().get_local_cache().persist_dir = str(demo_backup_directory(__file__))
    if stop.is_set():
        return {"stopped": True}
    context = await asyncio.to_thread(
        init_context_by_config, config, log_options=demo_log_options(__file__))
    provider, consumer = ProviderAPI(context), ConsumerAPI(context)
    registered = None
    try:
        if stop.is_set():
            return {"stopped": True}
        registered = await provider.async_register_instance(InstanceRegisterRequest(
            namespace=args.namespace, service=registration["name"], service_token=args.token,
            host=registration["host"], port=args.registration_port, protocol="",
            version=registration["version"], ttl=5, metadata=metadata))
        if stop.is_set():
            return {"stopped": True, "instance_id": registered.instance_id}
        deadline = time.monotonic() + 40
        found_registration = None
        last_mismatch = None
        while True:
            if stop.is_set():
                return {"stopped": True, "instance_id": registered.instance_id}
            try:
                snapshot = await _wait_for_completion_or_stop(
                    stop,
                    consumer.async_get_all_instances(
                        GetAllInstancesRequest(
                            namespace=args.namespace, service=registration["name"])),
                )
            except SDKError as error:
                retryable = (error.err_code == ErrorCode.ErrCodeAPITimeoutError
                              or (error.err_code == ErrorCode.ErrCodeServerError
                                  and "not found" in error.msg.lower()))
                if not retryable:
                    raise
                snapshot = None
            if snapshot is _STOPPED:
                return {"stopped": True, "instance_id": registered.instance_id}
            if stop.is_set():
                return {"stopped": True, "instance_id": registered.instance_id}
            node = None
            if snapshot is not None:
                node = find_registered_instance(snapshot.instances, registered.instance_id)
            if node is not None:
                try:
                    found_registration = validate_registered_instance(
                        node, card_text, args.a2a_version, args.registration_port)
                except (KeyError, TypeError, ValueError) as error:
                    last_mismatch = str(error)
                else:
                    break
            if time.monotonic() >= deadline:
                suffix = f": {last_mismatch}" if last_mismatch else ""
                raise RuntimeError(
                    "Registered A2A instance did not become discoverable" + suffix)
            if await _wait_for_stop(stop, 0.2):
                return {"stopped": True, "instance_id": registered.instance_id}
        found = node.get_metadata()
        result = {
            "agent": found_registration["name"],
            "a2a_version": found["ai-a2a-version"],
            "version": found_registration["version"],
            "transport": found_registration["interfaces"][0]["transport"],
            "endpoint": found_registration["interfaces"][0]["url"],
            "instances": len(snapshot.instances),
            "instance_id": registered.instance_id,
            "host": node.get_host(),
            "port": node.get_port(),
            "protocol": node.get_protocol(),
            "kept_running": args.keep_running,
        }
        print(json.dumps(result), flush=True)
        if args.keep_running:
            await stop.wait()
        else:
            await _wait_for_stop(stop, args.duration)
        return result
    finally:
        try:
            if registered is not None:
                await provider.async_deregister_instance(InstanceDeRegisterRequest(
                    namespace=args.namespace, service=registration["name"], service_token=args.token,
                    host=registration["host"], port=args.registration_port,
                    instance_id=registered.instance_id))
        finally:
            await asyncio.to_thread(context.destroy)


def registration_port(value):
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("registration port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("registration port must be in range 1..65535")
    return port


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("POLARIS_SERVER_ADDRESS", "127.0.0.1:8091"))
    parser.add_argument("--token", default=os.getenv("POLARIS_SERVICE_TOKEN", ""))
    parser.add_argument("--namespace", default="polaris-python-integration")
    parser.add_argument(
        "--registration-port", type=registration_port, default=1,
        help="Instance identity port; this is not the Agent listening port")
    parser.add_argument(
        "--a2a-version", choices=SUPPORTED_A2A_VERSIONS, default="1.0",
        help="Explicit AgentCard schema version")
    parser.add_argument(
        "--card",
        default=str(Path(__file__).resolve().parent / "config" / "a2a" / "agent-card.json"),
    )
    parser.add_argument("--duration", type=float, default=6)
    parser.add_argument("--keep-running", action="store_true")
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
