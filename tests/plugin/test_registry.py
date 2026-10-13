from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

from polaris_python.core.instance import ServiceInstance
from polaris_python.plugin.registry import InMemoryRegistry, PersistentRegistry

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

INSTANCE = response_pb2.DiscoverResponse.INSTANCE


def _snapshot(revision: str, *hosts: str) -> response_pb2.DiscoverResponse:
    return response_pb2.DiscoverResponse(
        code={"value": 200000},
        type=INSTANCE,
        service=service_pb2.Service(revision={"value": revision}),
        instances=[ServiceInstance(service="svc", host=host, port=80, id=host).to_proto("default") for host in hosts],
    )


async def _saved(path: Path, *snapshots: response_pb2.DiscoverResponse) -> None:
    registry = PersistentRegistry(path)
    for snapshot in snapshots:
        await registry.put_resource("default", "svc", INSTANCE, snapshot)
    await registry.close()


@pytest.mark.asyncio
async def test_persistent_registry_restores_snapshot_after_restart(tmp_path: Path) -> None:
    await _saved(tmp_path, _snapshot("r1", "a"))

    second = PersistentRegistry(tmp_path)
    restored = await second.restore_resource("default", "svc", INSTANCE)

    assert restored is not None
    assert restored.from_file
    assert restored.revision == "r1"
    assert [instance.id.value for instance in await second.get_instances("default", "svc")] == ["a"]


@pytest.mark.asyncio
async def test_persistent_registry_does_not_read_disk_until_restore(tmp_path: Path) -> None:
    await _saved(tmp_path, _snapshot("r1", "a"))

    assert await PersistentRegistry(tmp_path).get_resource("default", "svc", INSTANCE) is None


@pytest.mark.asyncio
async def test_registry_reports_unchanged_revision() -> None:
    registry = InMemoryRegistry()

    assert await registry.put_resource("default", "svc", INSTANCE, _snapshot("r1", "a"))
    assert not await registry.put_resource("default", "svc", INSTANCE, _snapshot("r1", "a"))
    assert await registry.put_resource("default", "svc", INSTANCE, _snapshot("r2", "b"))


@pytest.mark.asyncio
async def test_registry_compares_content_when_revision_is_missing() -> None:
    registry = InMemoryRegistry()

    assert await registry.put_resource("default", "svc", INSTANCE, _snapshot("", "a"))
    assert not await registry.put_resource("default", "svc", INSTANCE, _snapshot("", "a"))
    assert await registry.put_resource("default", "svc", INSTANCE, _snapshot("", "b"))


@pytest.mark.asyncio
async def test_server_snapshot_replaces_restored_snapshot_with_same_revision(tmp_path: Path) -> None:
    await _saved(tmp_path, _snapshot("r1", "a"))
    registry = PersistentRegistry(tmp_path)
    await registry.restore_resource("default", "svc", INSTANCE)

    assert await registry.put_resource("default", "svc", INSTANCE, _snapshot("r1", "a"))
    resource = await registry.get_resource("default", "svc", INSTANCE)
    assert resource is not None and not resource.from_file


@pytest.mark.asyncio
async def test_restore_keeps_server_snapshot(tmp_path: Path) -> None:
    await _saved(tmp_path, _snapshot("old", "a"))
    registry = PersistentRegistry(tmp_path)
    await registry.put_resource("default", "svc", INSTANCE, _snapshot("new", "b"))

    assert await registry.restore_resource("default", "svc", INSTANCE) is None
    assert [instance.id.value for instance in await registry.get_instances("default", "svc")] == ["b"]


@pytest.mark.asyncio
async def test_remove_resource_deletes_persisted_file_and_lock(tmp_path: Path) -> None:
    registry = PersistentRegistry(tmp_path)
    await registry.put_resource("default", "svc", INSTANCE, _snapshot("r1", "a"))
    await registry.flush()
    path = registry.path_for("default", "svc", INSTANCE)
    lock = path.with_name(f"{path.name}.lock")
    assert path.exists() and lock.exists()

    await registry.remove_resource("default", "svc", INSTANCE)
    await registry.flush()

    assert not path.exists() and not lock.exists()
    assert await registry.get_resource("default", "svc", INSTANCE) is None


@pytest.mark.asyncio
async def test_put_returns_before_the_backup_is_written(tmp_path: Path) -> None:
    registry = PersistentRegistry(tmp_path)
    gate = threading.Event()
    registry._worker.submit(gate.wait)

    assert await registry.put_resource("default", "svc", INSTANCE, _snapshot("r1", "a"))
    assert not registry.path_for("default", "svc", INSTANCE).exists()

    gate.set()
    await registry.close()
    assert registry.path_for("default", "svc", INSTANCE).exists()


@pytest.mark.asyncio
@pytest.mark.skipif(fcntl is None, reason="file locks need fcntl")
async def test_locked_backup_is_written_on_retry(tmp_path: Path) -> None:
    registry = PersistentRegistry(tmp_path, max_write_retry=1, retry_interval_seconds=0.2)
    path = registry.path_for("default", "svc", INSTANCE)
    with path.with_name(f"{path.name}.lock").open("a+b") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        await registry.put_resource("default", "svc", INSTANCE, _snapshot("r1", "a"))
        await asyncio.sleep(0.05)
        assert not path.exists()
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)

    await registry.flush()
    assert path.exists()


@pytest.mark.asyncio
@pytest.mark.skipif(fcntl is None, reason="file locks need fcntl")
async def test_backup_gives_up_while_another_process_holds_the_lock(tmp_path: Path) -> None:
    registry = PersistentRegistry(tmp_path, max_write_retry=1, retry_interval_seconds=0.01)
    path = registry.path_for("default", "svc", INSTANCE)
    with path.with_name(f"{path.name}.lock").open("a+b") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        await registry.put_resource("default", "svc", INSTANCE, _snapshot("r1", "a"))
        await registry.flush()

    assert not path.exists()


@pytest.mark.asyncio
async def test_restore_ignores_corrupt_snapshot_file(tmp_path: Path) -> None:
    registry = PersistentRegistry(tmp_path)
    path = registry.path_for("default", "svc", INSTANCE)
    path.write_text("{not json", encoding="utf-8")

    assert await registry.restore_resource("default", "svc", INSTANCE) is None


def test_snapshot_file_name_encodes_namespace_and_service(tmp_path: Path) -> None:
    path = PersistentRegistry(tmp_path).path_for("team/a", "svc#1", INSTANCE)

    assert path.name == "svc#team%2Fa#svc%231#instance.json"
