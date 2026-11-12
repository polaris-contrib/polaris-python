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
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._support import (
    demo_backup_directory,
    demo_log_options,
    wait_for_operation_or_stop,
    wait_for_stop,
)
from polaris import Configuration, ConsumerAPI, ProviderAPI, init_context_by_config
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.pkg.model.server import InstanceDeRegisterRequest, InstanceRegisterRequest
from polaris.pkg.model.service import GetAllInstancesRequest

A2A_V1_PATH = "/a2a/v1"
A2A_LEGACY_PATH = "/a2a/legacy"
A2A_REST_PATH = "/rest"
A2A_CONTENT_TYPE = "application/a2a+json"
AGENT_CARD_STATE = web.AppKey("agent_card_state", dict)


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


def endpoint_url(host, port, path):
    authority = f"[{host}]" if ":" in host else host
    return f"http://{authority}:{port}{path}"


def build_agent_card(card, a2a_version, host, port):
    """Build the final card from the actual listening address and port."""
    result = deepcopy(card)
    modern = {
        "url": endpoint_url(host, port, A2A_V1_PATH),
        "protocolBinding": "JSONRPC",
        "protocolVersion": "1.0",
    }
    legacy = {
        "url": endpoint_url(host, port, A2A_LEGACY_PATH),
        "protocolBinding": "JSONRPC",
        "protocolVersion": "0.3",
    }
    rest = {
        "url": endpoint_url(host, port, A2A_REST_PATH),
        "protocolBinding": "HTTP+JSON",
        "protocolVersion": "1.0",
    }
    if a2a_version == "1.0":
        for key in (
            "protocolVersion",
            "url",
            "preferredTransport",
            "additionalInterfaces",
        ):
            result.pop(key, None)
        result["supportedInterfaces"] = [modern, legacy, rest]
    else:
        result.pop("supportedInterfaces", None)
        result["protocolVersion"] = "0.3.0"
        result["url"] = legacy["url"]
        result["preferredTransport"] = "JSONRPC"
        result["additionalInterfaces"] = [
            {"url": modern["url"], "transport": "JSONRPC"},
            {"url": rest["url"], "transport": "HTTP+JSON"},
        ]
    result.pop("signatures", None)
    return result


def message_text(message):
    """Extract the first text part from a 0.3 or 1.0 A2A message."""
    for part in message.get("parts", []):
        text = part.get("text")
        if isinstance(text, str) and text:
            return text
    return ""


def message_response(message, *, schema_version, transport):
    """Return a deterministic echo message for one protocol flavor."""
    text = message_text(message)
    context_id = message.get("contextId") or message.get("context_id")
    task_id = message.get("taskId") or message.get("task_id")
    if schema_version == "0.3":
        result = {
            "role": "agent",
            "parts": [{
                "type": "text",
                "text": f"A2A 0.3 JSONRPC echo: {text}",
            }],
            "messageId": str(uuid.uuid4()),
        }
    else:
        result = {
            "kind": "message",
            "role": "ROLE_AGENT",
            "parts": [{"text": f"A2A {schema_version} {transport} echo: {text}"}],
            "messageId": str(uuid.uuid4()),
        }
    if context_id:
        result["contextId"] = context_id
    if task_id:
        result["taskId"] = task_id
    return result


def jsonrpc_error(request_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


async def handle_jsonrpc(request, *, schema_version):
    """Handle the message/send method for JSON-RPC 1.0 and 0.3 clients."""
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return web.json_response(
            jsonrpc_error(None, -32700, "Parse error"),
            status=400,
            content_type=A2A_CONTENT_TYPE,
        )
    if body.get("jsonrpc") != "2.0" or body.get("method") != "message/send":
        return web.json_response(
            jsonrpc_error(body.get("id"), -32601, "Method not found"),
            content_type=A2A_CONTENT_TYPE,
        )
    params = body.get("params")
    message = params.get("message") if isinstance(params, Mapping) else None
    if not isinstance(message, Mapping):
        return web.json_response(
            jsonrpc_error(body.get("id"), -32602, "Missing message parameter"),
            content_type=A2A_CONTENT_TYPE,
        )
    return web.json_response({
        "jsonrpc": "2.0",
        "id": body.get("id"),
        "result": message_response(
            message,
            schema_version=schema_version,
            transport="JSONRPC",
        ),
    }, content_type=A2A_CONTENT_TYPE)


async def handle_jsonrpc_v1(request):
    return await handle_jsonrpc(request, schema_version="1.0")


async def handle_jsonrpc_legacy(request):
    return await handle_jsonrpc(request, schema_version="0.3")


async def handle_rest(request):
    """Handle the 1.0 HTTP+JSON message-send binding."""
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return web.json_response(
            {"error": "invalid JSON"},
            status=400,
            content_type=A2A_CONTENT_TYPE,
        )
    message = body.get("message", body)
    if not isinstance(message, Mapping):
        return web.json_response(
            {"error": "message must be an object"},
            status=400,
            content_type=A2A_CONTENT_TYPE,
        )
    return web.json_response(
        message_response(message, schema_version="1.0", transport="HTTP+JSON"),
        content_type=A2A_CONTENT_TYPE,
    )


async def agent_card(request):
    card = request.app[AGENT_CARD_STATE].get("card")
    if card is None:
        return web.json_response(
            {"error": "AgentCard is not initialized"},
            status=503,
            content_type=A2A_CONTENT_TYPE,
        )
    return web.json_response(
        card,
        content_type=A2A_CONTENT_TYPE,
    )


async def start_a2a_server(host, port):
    """Start the three public A2A bindings and return the bound port."""
    app = web.Application()
    app[AGENT_CARD_STATE] = {}
    app.router.add_get("/.well-known/agent-card.json", agent_card)
    app.router.add_post(A2A_V1_PATH, handle_jsonrpc_v1)
    app.router.add_post(A2A_LEGACY_PATH, handle_jsonrpc_legacy)
    app.router.add_post(A2A_REST_PATH, handle_rest)
    app.router.add_post(f"{A2A_REST_PATH}/v1/message:send", handle_rest)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        site = web.TCPSite(runner, host, port)
        await site.start()
        bound_port = site._server.sockets[0].getsockname()[1]
        return app, runner, bound_port
    except BaseException:
        await runner.cleanup()
        raise


def retryable_discovery_error(error):
    """Return whether discovery can retry this transient SDK failure."""
    return (
        error.err_code in (
            ErrorCode.ErrCodeAPITimeoutError,
            ErrorCode.ErrCodeNetworkError,
            ErrorCode.ErrCodeAPIInstanceNotFound,
        )
        or (
            error.err_code == ErrorCode.ErrCodeServerError
            and "not found" in error.msg.lower()
        )
    )


def registration_mismatch(node, card, card_text, a2a_version, host, port):
    """Describe why a discovered instance is not the current registration."""
    metadata = node.get_metadata()
    if not isinstance(metadata, Mapping):
        return "instance metadata is not an object"
    if metadata.get("ai-agent-name") != card["name"]:
        return "ai-agent-name does not match the current AgentCard"
    if metadata.get("ai-agent-card") != card_text:
        return "registered AgentCard is stale"
    if metadata.get("ai-a2a-version") != a2a_version:
        return "registered A2A schema version is stale"
    if node.get_version() != card["version"]:
        return "instance version is stale"
    if node.get_host() != host:
        return "instance host does not match the AgentCard interface"
    if node.get_port() != port:
        return "instance port does not match registration_port"
    if node.get_protocol() != "":
        return "A2A instance protocol must be empty"
    return None


async def wait_for_registration(
        consumer, *, namespace, service, instance_id, card, card_text,
        a2a_version, host, port, stop):
    """Wait until discovery reflects the AgentCard from this registration."""
    deadline = time.monotonic() + 10
    last_mismatch = "instance not found"
    while time.monotonic() < deadline:
        if stop.is_set():
            return None
        try:
            completed, snapshot = await wait_for_operation_or_stop(
                stop,
                consumer.async_get_all_instances(
                    GetAllInstancesRequest(namespace=namespace, service=service),
                ),
            )
        except SDKError as error:
            if not retryable_discovery_error(error):
                raise
            snapshot = None
        else:
            if not completed:
                return None
            if stop.is_set():
                return None
            node = next(
                (item for item in snapshot.instances if item.get_id() == instance_id),
                None,
            )
            if node is not None:
                mismatch = registration_mismatch(
                    node, card, card_text, a2a_version, host, port)
                if mismatch is None:
                    return snapshot, node
                last_mismatch = mismatch
        if await wait_for_stop(stop, 0.2):
            return None
    if stop.is_set():
        return None
    raise RuntimeError(
        f"instance {instance_id} did not expose the current AgentCard: {last_mismatch}")


async def run(args):
    base_card = json.loads(Path(args.card).read_text(encoding="utf-8"))
    runner = None
    context = None
    provider = None
    registered = None
    stop = asyncio.Event()
    try:
        if getattr(args, "serve", False):
            listen_host = getattr(args, "host", "127.0.0.1")
            listen_port = getattr(args, "port", 0)
            app, runner, bound_port = await start_a2a_server(listen_host, listen_port)
            card = build_agent_card(
                base_card, args.a2a_version, listen_host, bound_port)
            app[AGENT_CARD_STATE]["card"] = card
            card_text = json.dumps(card, ensure_ascii=False)
        else:
            card = base_card
            card_text = json.dumps(card, ensure_ascii=False)
            bound_port = None

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
            registration = await wait_for_registration(
                consumer,
                namespace=args.namespace,
                service=card["name"],
                instance_id=registered.instance_id,
                card=card,
                card_text=card_text,
                a2a_version=args.a2a_version,
                host=host,
                port=args.registration_port,
                stop=stop,
            )
            if registration is None:
                return
            snapshot, node = registration
            print(json.dumps({
                "agent": node.get_metadata()["ai-agent-name"],
                "a2a_version": node.get_metadata()["ai-a2a-version"],
                "version": node.get_version(),
                "transport": transport,
                "endpoint": endpoint,
                "instances": len(snapshot.instances),
                "instance_id": registered.instance_id,
                "host": node.get_host(),
                "port": node.get_port(),
                "protocol": node.get_protocol(),
                "listen_port": bound_port,
                "endpoints": {
                    "jsonrpc_v1": endpoint_url(host, bound_port, A2A_V1_PATH)
                    if bound_port is not None else None,
                    "jsonrpc_v03": endpoint_url(host, bound_port, A2A_LEGACY_PATH)
                    if bound_port is not None else None,
                    "http_json_v1": endpoint_url(host, bound_port, A2A_REST_PATH)
                    if bound_port is not None else None,
                },
            }), flush=True)
            if args.keep_running:
                await stop.wait()
            else:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=args.duration)
                except TimeoutError:
                    pass
    finally:
        try:
            if registered is not None:
                await provider.async_deregister_instance(InstanceDeRegisterRequest(
                    namespace=args.namespace,
                    service=card["name"],
                    service_token=args.token,
                    host=host,
                    port=args.registration_port,
                    instance_id=registered.instance_id,
                ))
        finally:
            try:
                if context is not None:
                    await asyncio.to_thread(context.destroy)
            finally:
                if runner is not None:
                    await runner.cleanup()


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
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--serve", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--registration-port", type=registration_port, default=1)
    parser.add_argument("--duration", type=float, default=6)
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args(argv)
    if args.duration < 0:
        parser.error("duration must be nonnegative")
    if not 0 <= args.port <= 65535:
        parser.error("port must be in range 0..65535")
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
