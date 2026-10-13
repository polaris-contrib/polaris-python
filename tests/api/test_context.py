from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from google.protobuf.wrappers_pb2 import StringValue
from polarismesh_specification.api.v1.model import model_pb2
from polarismesh_specification.api.v1.service_manage import request_pb2, response_pb2, service_pb2
from polarismesh_specification.api.v1.traffic_manage import ratelimit_pb2, routing_pb2

from polaris_python.api.consumer import ConsumerAPI
from polaris_python.api.context import SDKContext
from polaris_python.core.config import Config
from polaris_python.core.error import PolarisTransportError
from polaris_python.core.instance import ServiceInstance
from polaris_python.plugin.ratelimiter import RateLimiter
from polaris_python.plugin.registry import InMemoryRegistry, PersistentRegistry

INSTANCE = response_pb2.DiscoverResponse.INSTANCE
ROUTING = response_pb2.DiscoverResponse.ROUTING
RATE_LIMIT = response_pb2.DiscoverResponse.RATE_LIMIT


class ScriptedConnector:
    """Answer each discover type once, then keep the stream open like Polaris.

    ``silent`` types never get an answer, as when the server is unreachable.
    Other unscripted types get an empty success response.
    """

    def __init__(
        self,
        responses: dict[int, response_pb2.DiscoverResponse] | None = None,
        *,
        silent: bool = False,
    ) -> None:
        self.responses = responses or {}
        self.silent = silent

    async def discover(self, request: request_pb2.DiscoverRequest) -> AsyncIterator[response_pb2.DiscoverResponse]:
        response = self.responses.get(request.type)
        if response is None and not self.silent:
            response = response_pb2.DiscoverResponse(code={"value": 200000}, type=request.type)
        if response is not None:
            yield response
        await asyncio.Event().wait()

    async def close(self) -> None:
        pass


def _instances(revision: str, *hosts: str) -> response_pb2.DiscoverResponse:
    return response_pb2.DiscoverResponse(
        code={"value": 200000},
        type=INSTANCE,
        service=service_pb2.Service(revision={"value": revision}),
        instances=[
            ServiceInstance(service="svc", namespace="prod", host=host, port=80, id=host).to_proto()
            for host in hosts
        ],
    )


def _rate_limit(revision: str) -> response_pb2.DiscoverResponse:
    rule = ratelimit_pb2.Rule(
        service={"value": "svc"},
        namespace={"value": "prod"},
        amounts=[ratelimit_pb2.Amount(maxAmount={"value": 1}, validDuration={"seconds": 1})],
    )
    return response_pb2.DiscoverResponse(
        code={"value": 200000},
        type=RATE_LIMIT,
        service=service_pb2.Service(revision={"value": revision}),
        rateLimit=ratelimit_pb2.RateLimit(rules=[rule]),
    )


async def _persist(path: Path, *responses: response_pb2.DiscoverResponse) -> None:
    registry = PersistentRegistry(path)
    for response in responses:
        await registry.put_resource("prod", "svc", int(response.type), response)
    await registry.close()


@pytest.mark.asyncio
async def test_consumer_uses_persisted_snapshot_when_server_does_not_answer(tmp_path: Path) -> None:
    await _persist(tmp_path, _instances("r1", "a"))
    context = SDKContext(
        Config(namespace="prod", timeout_seconds=0.1),
        connector=ScriptedConnector(silent=True),
        registry=PersistentRegistry(tmp_path),
    )

    instances = await ConsumerAPI(context).async_get_all_instances("svc")

    assert [item.id for item in instances] == ["a"]
    await context.async_destroy()


@pytest.mark.asyncio
async def test_consumer_raises_when_server_does_not_answer_and_nothing_is_cached() -> None:
    context = SDKContext(
        Config(namespace="prod", timeout_seconds=0.1),
        connector=ScriptedConnector(silent=True),
        registry=InMemoryRegistry(),
    )

    with pytest.raises(PolarisTransportError):
        await ConsumerAPI(context).async_get_all_instances("svc")
    await context.async_destroy()


@pytest.mark.asyncio
async def test_degraded_resource_is_not_waited_on_again(tmp_path: Path) -> None:
    await _persist(tmp_path, _instances("r1", "a"))
    context = SDKContext(
        Config(namespace="prod", timeout_seconds=0.3),
        connector=ScriptedConnector(silent=True),
        registry=PersistentRegistry(tmp_path),
    )
    consumer = ConsumerAPI(context)
    await consumer.async_get_all_instances("svc")

    started = time.monotonic()
    await consumer.async_get_all_instances("svc")

    assert time.monotonic() - started < 0.15
    await context.async_destroy()


@pytest.mark.asyncio
async def test_server_snapshot_replaces_persisted_snapshot(tmp_path: Path) -> None:
    await _persist(tmp_path, _instances("old", "a"))
    registry = PersistentRegistry(tmp_path)
    context = SDKContext(
        Config(namespace="prod"),
        connector=ScriptedConnector({INSTANCE: _instances("new", "b")}),
        registry=registry,
    )

    instances = await ConsumerAPI(context).async_get_all_instances("svc")
    await registry.flush()

    assert [item.id for item in instances] == ["b"]
    restored = PersistentRegistry(tmp_path)
    resource = await restored.restore_resource("prod", "svc", INSTANCE)
    assert resource is not None and resource.revision == "new"
    await context.async_destroy()


@pytest.mark.asyncio
async def test_persisted_rules_apply_when_server_does_not_answer(tmp_path: Path) -> None:
    await _persist(tmp_path, _instances("r1", "a"), _rate_limit("rl-1"))
    context = SDKContext(
        Config(namespace="prod", timeout_seconds=0.1),
        connector=ScriptedConnector(silent=True),
        registry=PersistentRegistry(tmp_path),
    )

    await ConsumerAPI(context).async_get_all_instances("svc")

    assert [rule.key for rule in context.rate_limiter.rules] == ["prod/svc"]
    await context.async_destroy()


@pytest.mark.asyncio
async def test_first_call_applies_routing_rules() -> None:
    matcher = model_pb2.MatchString(value=StringValue(value="pre"))
    routing = response_pb2.DiscoverResponse(
        code={"value": 200000},
        type=ROUTING,
        routing=routing_pb2.Routing(
            inbounds=[
                routing_pb2.Route(
                    sources=[routing_pb2.Source(metadata={"$query.env": matcher})],
                    destinations=[routing_pb2.Destination(metadata={"env": matcher})],
                )
            ]
        ),
    )
    instances = _instances("r1")
    for host, env in (("a", "dev"), ("b", "pre")):
        instances.instances.append(
            ServiceInstance(service="svc", namespace="prod", host=host, port=80, id=host, metadata={"env": env}).to_proto()
        )
    context = SDKContext(
        Config(namespace="prod"),
        connector=ScriptedConnector({INSTANCE: instances, ROUTING: routing}),
        registry=InMemoryRegistry(),
    )

    selected = await ConsumerAPI(context).async_get_all_instances("svc", query={"env": "pre"})

    assert [item.id for item in selected] == ["b"]
    await context.async_destroy()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [400301, 400202])
async def test_service_not_found_removes_cached_snapshot(tmp_path: Path, code: int) -> None:
    registry = PersistentRegistry(tmp_path)
    await registry.put_resource("prod", "svc", INSTANCE, _instances("r1", "a"))
    context = SDKContext(Config(namespace="prod"), connector=ScriptedConnector(), registry=registry)
    not_found = response_pb2.DiscoverResponse(code={"value": code}, type=INSTANCE)

    await context._apply_discover_response("prod", "svc", INSTANCE, not_found)
    await registry.flush()

    assert await registry.get_resource("prod", "svc", INSTANCE) is None
    assert not registry.path_for("prod", "svc", INSTANCE).exists()
    await context.async_destroy()


@pytest.mark.asyncio
async def test_zero_protection_keeps_instances_on_empty_push() -> None:
    registry = InMemoryRegistry()
    context = SDKContext(Config(namespace="prod", zero_protection=True), connector=ScriptedConnector(), registry=registry)

    await context._apply_discover_response("prod", "svc", INSTANCE, _instances("r1", "a"))
    await context._apply_discover_response("prod", "svc", INSTANCE, _instances("r2"))

    assert [item.id.value for item in await registry.get_instances("prod", "svc")] == ["a"]
    await context.async_destroy()


@pytest.mark.asyncio
async def test_empty_push_clears_instances_without_zero_protection() -> None:
    registry = InMemoryRegistry()
    context = SDKContext(Config(namespace="prod"), connector=ScriptedConnector(), registry=registry)

    await context._apply_discover_response("prod", "svc", INSTANCE, _instances("r1", "a"))
    await context._apply_discover_response("prod", "svc", INSTANCE, _instances("r2"))

    assert await registry.get_instances("prod", "svc") == []
    await context.async_destroy()


@pytest.mark.asyncio
async def test_changed_snapshot_is_recorded_on_cache_channel(tmp_path: Path) -> None:
    context = SDKContext(
        Config(namespace="prod", log_dir=str(tmp_path)),
        connector=ScriptedConnector(),
        registry=InMemoryRegistry(),
    )

    await context._apply_discover_response("prod", "svc", INSTANCE, _instances("r1", "a"))
    await context._apply_discover_response("prod", "svc", INSTANCE, _instances("r1", "a"))

    text = (tmp_path / "cache" / "polaris-cache.log").read_text(encoding="utf-8")
    assert text.count("INSTANCE prod/svc revision None -> 'r1' instances=1 source=server") == 1
    await context.async_destroy()


class CountingRateLimiter(RateLimiter):
    def __init__(self) -> None:
        super().__init__()
        self.updates = 0

    def update_from_proto(self, rate_limit: ratelimit_pb2.RateLimit) -> None:
        self.updates += 1
        super().update_from_proto(rate_limit)


@pytest.mark.asyncio
async def test_unchanged_rule_snapshot_is_not_reapplied() -> None:
    limiter = CountingRateLimiter()
    context = SDKContext(
        Config(namespace="prod"),
        connector=ScriptedConnector(),
        registry=InMemoryRegistry(),
        rate_limiter=limiter,
    )

    await context._apply_discover_response("prod", "svc", RATE_LIMIT, _rate_limit("rl-1"))
    await context._apply_discover_response("prod", "svc", RATE_LIMIT, _rate_limit("rl-1"))

    assert limiter.updates == 1
    await context.async_destroy()


def _expiring_context(registry: InMemoryRegistry, expire_seconds: float = 60.0) -> SDKContext:
    return SDKContext(
        Config(namespace="prod", service_expire_enable=True, service_expire_seconds=expire_seconds),
        connector=ScriptedConnector({INSTANCE: _instances("r1", "a")}),
        registry=registry,
    )


@pytest.mark.asyncio
async def test_idle_service_is_removed_from_memory_and_disk(tmp_path: Path) -> None:
    registry = PersistentRegistry(tmp_path)
    context = _expiring_context(registry)
    await ConsumerAPI(context).async_get_all_instances("svc")
    context._last_access[("prod", "svc")] -= 61

    await context._expire_idle_services()
    await registry.flush()

    assert await registry.get_resource("prod", "svc", INSTANCE) is None
    assert not registry.path_for("prod", "svc", INSTANCE).exists()
    assert not [key for key in context._watches if key[:2] == ("prod", "svc")]
    await context.async_destroy()


@pytest.mark.asyncio
async def test_recently_read_service_is_kept() -> None:
    registry = InMemoryRegistry()
    context = _expiring_context(registry)
    await ConsumerAPI(context).async_get_all_instances("svc")

    await context._expire_idle_services()

    assert await registry.get_resource("prod", "svc", INSTANCE) is not None
    await context.async_destroy()


@pytest.mark.asyncio
async def test_expired_service_is_discovered_again_on_next_read() -> None:
    context = _expiring_context(InMemoryRegistry())
    consumer = ConsumerAPI(context)
    await consumer.async_get_all_instances("svc")
    context._last_access[("prod", "svc")] -= 61
    await context._expire_idle_services()

    instances = await consumer.async_get_all_instances("svc")

    assert [item.id for item in instances] == ["a"]
    await context.async_destroy()


@pytest.mark.asyncio
async def test_expiry_scan_runs_every_expire_interval() -> None:
    registry = InMemoryRegistry()
    context = _expiring_context(registry, expire_seconds=0.05)
    await ConsumerAPI(context).async_get_all_instances("svc")

    await asyncio.sleep(0.2)

    assert await registry.get_resource("prod", "svc", INSTANCE) is None
    await context.async_destroy()


@pytest.mark.asyncio
async def test_expiry_is_off_by_default() -> None:
    context = SDKContext(Config(namespace="prod"), connector=ScriptedConnector(), registry=InMemoryRegistry())

    await ConsumerAPI(context).async_get_all_instances("svc")

    assert context._expire_task is None
    await context.async_destroy()
