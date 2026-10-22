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

import pytest

from polaris.api.config import SDKContext
from polaris.api.config import init_context_by_stream
from polaris.api.consumer import ConsumerAPI
from polaris.api.provider import ProviderAPI
from polaris.pkg.config.api import Configuration
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.pkg.model.server import InstanceRegisterRequest, InstanceRegisterResponse
from polaris.pkg.model.service import GetInstancesRequest
from polaris.plugin_manager import PluginManager


class FakeEngine:
    """Record calls made by the public API."""

    def __init__(self) -> None:
        self.requests = []
        self.destroyed = False

    def sync_register(self, request):
        self.requests.append(request)
        return InstanceRegisterResponse("instance-id")

    async def async_register(self, request):
        return self.sync_register(request)

    async def async_get_instances(self, req):
        request = req
        self.requests.append(request)
        return "instances"

    def sync_get_instances(self, request):
        self.requests.append(request)
        return "instances"

    def destroy(self):
        self.destroyed = True


@pytest.mark.asyncio
async def test_provider_register_delegates_to_engine() -> None:
    engine = FakeEngine()
    context = SDKContext(Configuration(), PluginManager(), engine)
    provider = ProviderAPI(context)
    request = InstanceRegisterRequest("svc", "token", "ns", "127.0.0.1", 8080)

    response = await provider.async_register(request)

    assert response.instance_id == "instance-id"
    assert engine.requests == [request]


@pytest.mark.asyncio
async def test_consumer_sync_and_async_use_same_engine() -> None:
    engine = FakeEngine()
    consumer = ConsumerAPI(SDKContext(Configuration(), PluginManager(), engine))
    request = GetInstancesRequest(service="svc", namespace="ns")

    assert consumer.get_instances(request) == "instances"
    assert await consumer.async_get_instances(request) == "instances"
    assert engine.requests == [request, request]


def test_api_rejects_destroyed_context() -> None:
    engine = FakeEngine()
    context = SDKContext(Configuration(), PluginManager(), engine)
    consumer = ConsumerAPI(context)
    context.destroy()

    with pytest.raises(SDKError) as raised:
        consumer.get_instances(GetInstancesRequest(service="svc", namespace="ns"))

    assert raised.value.err_code == ErrorCode.ErrCodeInvalidStateError
    assert engine.destroyed is True


def test_init_context_by_stream_loads_configuration(monkeypatch) -> None:
    class FakeEngine:
        def destroy(self):
            pass

    monkeypatch.setattr(
        "polaris.api.config.create_flow_engine",
        lambda config, plugins, global_ctx: FakeEngine(),
    )

    context = init_context_by_stream(
        """
global:
  serverConnector:
    addresses: [127.0.0.1:8091]
    connectTimeout: 1000ms
  api:
    bindIP: 127.0.0.1
        """,
        apply_env=False,
    )

    try:
        assert context.get_config().get_global().get_server_connector().get_connect_timeout() == 1000
        assert context.get_config().get_global().get_server_connector().get_addresses() == ["127.0.0.1:8091"]
    finally:
        context.destroy()
