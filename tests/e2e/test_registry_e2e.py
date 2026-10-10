"""E2E validation against a real Polaris service-management endpoint."""

from __future__ import annotations

import asyncio
import os
import socket
import time
from dataclasses import replace
from uuid import uuid4

import pytest

from polaris_python import Config, SDKContext, ServiceInstance
from polaris_python.api.consumer import ConsumerAPI
from polaris_python.api.provider import ProviderAPI


def _e2e_enabled() -> bool:
    return os.getenv("POLARIS_E2E", "").lower() in {"1", "true", "yes"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.skipif(not _e2e_enabled(), reason="set POLARIS_E2E=1 to run against Polaris")
async def test_register_discover_heartbeat_and_deregister() -> None:
    """Validate the complete instance lifecycle against Polaris."""
    config = Config.from_env()
    namespace = os.getenv("POLARIS_E2E_NAMESPACE", config.namespace or "default")
    service = os.getenv("POLARIS_E2E_SERVICE", f"polaris-python-e2e-{uuid4().hex[:10]}")
    timeout = float(os.getenv("POLARIS_E2E_TIMEOUT", "20"))
    context = SDKContext(replace(config, namespace=namespace))
    provider = ProviderAPI(context)
    consumer = ConsumerAPI(context)
    instance = ServiceInstance(
        service=service,
        namespace=namespace,
        host="127.0.0.1",
        port=_free_port(),
        id=f"python-e2e-{uuid4().hex}",
        resource_type="e2e",
        protocol="http",
        version="e2e",
        ttl_seconds=30,
    )
    registered = None
    try:
        registered = await provider.async_register_instance(instance)
        deadline = time.monotonic() + timeout
        discovered = []
        found = False
        while time.monotonic() < deadline:
            discovered = await consumer.async_get_all_instances(service, namespace=namespace)
            found = any(
                item.id == registered.id
                or (item.host == instance.host and item.port == instance.port)
                for item in discovered
            )
            if found:
                break
            await asyncio.sleep(0.25)
        assert found, f"instance {namespace}/{service}/{instance.id} was not discovered: {discovered}"
        await provider.async_heartbeat(registered)
        await provider.async_deregister_instance(registered)
        await asyncio.sleep(0.5)
    finally:
        if registered is not None:
            try:
                await provider.async_deregister_instance(registered)
            except Exception:
                pass
        await context.async_destroy()
