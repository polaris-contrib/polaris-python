from __future__ import annotations

import pytest

from polaris_python.core.instance import ServiceInstance
from polaris_python.plugin.registry import JsonFileRegistry


@pytest.mark.asyncio
async def test_json_registry_persists_instance(tmp_path) -> None:
    path = tmp_path / "registry.json"
    instance = ServiceInstance(service="svc", host="localhost", port=1, id="i-1").to_proto("default")

    first = JsonFileRegistry(path)
    await first.put_instances("default", "svc", [instance])

    second = JsonFileRegistry(path)
    cached = await second.get_instances("default", "svc")
    assert cached[0].id.value == "i-1"
    assert cached[0].namespace.value == "default"
