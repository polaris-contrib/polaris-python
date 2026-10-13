from __future__ import annotations

import asyncio

import pytest
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

from polaris_python.api.context import SDKContext
from polaris_python.api.provider import ProviderAPI
from polaris_python.core.config import Config
from polaris_python.core.instance import ServiceInstance
from polaris_python.plugin.registry import InMemoryRegistry


class HeartbeatConnector:
    """Assign ``id-N`` on each registration and answer heartbeats with scripted codes."""

    def __init__(self, heartbeat_codes: list[int] | None = None) -> None:
        self.heartbeat_codes = list(heartbeat_codes or [])
        self.registered: list[service_pb2.Instance] = []
        self.deregistered: list[service_pb2.Instance] = []
        self.heartbeats: list[service_pb2.Instance] = []

    async def register_instance(self, instance: service_pb2.Instance) -> response_pb2.Response:
        self.registered.append(instance)
        registered = service_pb2.Instance()
        registered.CopyFrom(instance)
        registered.id.value = f"id-{len(self.registered)}"
        return response_pb2.Response(code={"value": 200000}, instance=registered)

    async def deregister_instance(self, instance: service_pb2.Instance) -> response_pb2.Response:
        self.deregistered.append(instance)
        return response_pb2.Response(code={"value": 200000})

    async def heartbeat(self, instance: service_pb2.Instance) -> response_pb2.Response:
        self.heartbeats.append(instance)
        code = self.heartbeat_codes.pop(0) if self.heartbeat_codes else 200000
        return response_pb2.Response(code={"value": code})

    async def close(self) -> None:
        pass


def _context(connector: HeartbeatConnector, **config: object) -> SDKContext:
    return SDKContext(Config(namespace="prod", **config), connector=connector, registry=InMemoryRegistry())


def _instance(**values: object) -> ServiceInstance:
    return ServiceInstance(service="svc", host="127.0.0.1", port=8080, **values)


@pytest.mark.asyncio
async def test_register_fills_default_ttl_and_starts_heartbeat() -> None:
    connector = HeartbeatConnector()
    context = _context(connector)

    await ProviderAPI(context).async_register_instance(_instance())

    assert connector.registered[0].health_check.heartbeat.ttl.value == 5
    assert len(context.register_flow._states) == 1
    await context.async_destroy()
    assert not context.register_flow._states


@pytest.mark.asyncio
async def test_registered_instance_heartbeats_every_ttl_with_server_id() -> None:
    connector = HeartbeatConnector()
    context = _context(connector)
    provider = ProviderAPI(context)
    registered = await provider.async_register_instance(_instance(ttl_seconds=1))

    await asyncio.sleep(1.2)

    assert [item.id.value for item in connector.heartbeats] == ["id-1"]
    await provider.async_deregister_instance(registered)
    await context.async_destroy()


@pytest.mark.asyncio
async def test_deregister_stops_the_heartbeat_task() -> None:
    connector = HeartbeatConnector()
    context = _context(connector)
    provider = ProviderAPI(context)
    registered = await provider.async_register_instance(_instance())
    task = next(iter(context.register_flow._states.values())).heartbeat_task

    await provider.async_deregister_instance(registered)

    assert task is not None and task.done()
    assert not context.register_flow._states
    await context.async_destroy()


@pytest.mark.asyncio
async def test_instance_without_health_check_gets_no_heartbeat() -> None:
    connector = HeartbeatConnector()
    context = _context(connector)

    await ProviderAPI(context).async_register_instance(_instance(enable_health_check=False))

    assert not connector.registered[0].health_check.heartbeat.HasField("ttl")
    assert not context.register_flow._states
    await context.async_destroy()


@pytest.mark.asyncio
async def test_two_not_found_heartbeats_register_the_instance_again() -> None:
    connector = HeartbeatConnector([400202, 400202])
    context = _context(connector, min_register_interval_seconds=0)
    await ProviderAPI(context).async_register_instance(_instance(ttl_seconds=60))
    state = next(iter(context.register_flow._states.values()))

    await context.register_flow._run_heartbeat(state)
    await context.register_flow._run_heartbeat(state)
    assert state.reregister_task is not None
    await state.reregister_task

    assert len(connector.registered) == 2
    assert state.instance_id == "id-2"
    assert state.failures == 0 and state.reregisters == 0
    await context.async_destroy()


@pytest.mark.asyncio
async def test_not_found_soon_after_first_registration_does_not_register_again() -> None:
    connector = HeartbeatConnector([400202, 400202])
    context = _context(connector)
    await ProviderAPI(context).async_register_instance(_instance(ttl_seconds=60))
    state = next(iter(context.register_flow._states.values()))

    await context.register_flow._run_heartbeat(state)
    await context.register_flow._run_heartbeat(state)

    assert state.reregister_task is None
    assert len(connector.registered) == 1
    await context.async_destroy()


@pytest.mark.asyncio
async def test_other_heartbeat_errors_reset_the_not_found_count() -> None:
    connector = HeartbeatConnector([400202, 500000, 400202])
    context = _context(connector, min_register_interval_seconds=0)
    await ProviderAPI(context).async_register_instance(_instance(ttl_seconds=60))
    state = next(iter(context.register_flow._states.values()))

    for _ in range(3):
        await context.register_flow._run_heartbeat(state)

    assert state.failures == 1
    assert state.reregister_task is None
    await context.async_destroy()
