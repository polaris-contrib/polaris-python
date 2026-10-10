from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

from polaris_python.api.consumer import ConsumerAPI
from polaris_python.api.context import SDKContext
from polaris_python.api.provider import ProviderAPI
from polaris_python.core.config import Config
from polaris_python.core.error import PolarisError
from polaris_python.core.instance import ServiceInstance
from polaris_python.plugin.registry import InMemoryRegistry


class FakeConnector:
    def __init__(self, instances: list[service_pb2.Instance]) -> None:
        self.instances = instances
        self.registered: list[service_pb2.Instance] = []
        self.deregistered: list[service_pb2.Instance] = []
        self.heartbeats: list[service_pb2.Instance] = []

    async def register_instance(self, instance: service_pb2.Instance) -> response_pb2.Response:
        self.registered.append(instance)
        return response_pb2.Response(code={"value": 200000})

    async def deregister_instance(self, instance: service_pb2.Instance) -> response_pb2.Response:
        self.deregistered.append(instance)
        return response_pb2.Response(code={"value": 200000})

    async def heartbeat(self, instance: service_pb2.Instance) -> response_pb2.Response:
        self.heartbeats.append(instance)
        return response_pb2.Response(code={"value": 200000})

    async def discover(self, request: object) -> AsyncIterator[response_pb2.DiscoverResponse]:
        yield response_pb2.DiscoverResponse(
            code={"value": 200000},
            type="INSTANCE",
            instances=self.instances,
        )

    async def close(self) -> None:
        pass


@pytest.fixture
def instance() -> ServiceInstance:
    return ServiceInstance(
        service="agent-service",
        namespace="prod",
        id="agent-1",
        host="127.0.0.1",
        port=8080,
        protocol="http",
        version="v1",
        metadata={"polaris.resource.type": "agent", "team": "ai"},
    )


@pytest.mark.asyncio
async def test_provider_register_deregister_and_heartbeat(instance: ServiceInstance) -> None:
    connector = FakeConnector([])
    context = SDKContext(Config(namespace="prod"), connector=connector, registry=InMemoryRegistry())
    provider = ProviderAPI(context)

    registered = await provider.async_register_instance(instance)
    await provider.async_heartbeat(instance)
    await provider.async_deregister_instance(instance)

    assert registered.id == "agent-1"
    assert connector.registered[0].metadata["polaris.protocol"] == "http"
    assert connector.heartbeats[0].namespace.value == "prod"
    assert connector.deregistered[0].service.value == "agent-service"
    await context.async_destroy()


def test_sync_provider_facade(instance: ServiceInstance) -> None:
    connector = FakeConnector([])
    context = SDKContext(Config(namespace="prod"), connector=connector, registry=InMemoryRegistry())
    provider = ProviderAPI(context)

    registered = provider.register_instance(instance)
    provider.heartbeat(registered)
    provider.deregister_instance(registered)

    assert registered.id == "agent-1"
    assert connector.heartbeats[0].namespace.value == "prod"
    context.destroy()


@pytest.mark.asyncio
async def test_consumer_discovers_and_filters_instances(instance: ServiceInstance) -> None:
    isolated = ServiceInstance(
        service="agent-service",
        namespace="prod",
        id="agent-2",
        host="127.0.0.2",
        port=8080,
        isolate=True,
        metadata={"polaris.resource.type": "agent"},
    )
    connector = FakeConnector([instance.to_proto(), isolated.to_proto()])
    context = SDKContext(Config(namespace="prod"), connector=connector, registry=InMemoryRegistry())
    consumer = ConsumerAPI(context)

    all_instances = await consumer.async_get_all_instances("agent-service", resource_type="agent")
    healthy = await consumer.async_get_healthy_instances("agent-service", protocol="http", version="v1")

    assert [item.id for item in all_instances] == ["agent-1"]
    assert [item.id for item in healthy] == ["agent-1"]
    await context.async_destroy()


def test_sync_consumer_facade(instance: ServiceInstance) -> None:
    connector = FakeConnector([instance.to_proto()])
    context = SDKContext(Config(namespace="prod"), connector=connector, registry=InMemoryRegistry())

    selected = ConsumerAPI(context).get_one_instance("agent-service")
    selected_again = ConsumerAPI(context).get_one_instance("agent-service")

    assert selected.id == "agent-1"
    assert selected_again.id == "agent-1"
    context.destroy()


@pytest.mark.asyncio
async def test_api_rejects_destroyed_context(instance: ServiceInstance) -> None:
    context = SDKContext(Config(namespace="prod"), connector=FakeConnector([]), registry=InMemoryRegistry())
    await context.async_destroy()

    with pytest.raises(PolarisError, match="destroyed"):
        await ProviderAPI(context).async_heartbeat(instance)
