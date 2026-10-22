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

import asyncio
import json
import os
import threading
import time

import pytest
from google.protobuf import json_format
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

from polaris.pkg.config.api import Configuration
from polaris.pkg.model.context import ContextKeyEngine, new_value_context
from polaris.pkg.model.core import EventType, ServiceEventKey
from polaris.pkg.model.server import InstanceDiscoverRequest
from polaris.plugin.local_registry import file_cache as filecache
from polaris.plugin.local_registry import local_cache as localcache
from polaris.plugin.local_registry.local_cache import (
    CacheObject,
    InstanceFilter,
    LocalCache,
    ServiceUpdateRequest,
)
from polaris.plugin_manager import InitContext


class FakeFileCache:
    """Disable disk I/O while recording writes."""

    def __init__(self) -> None:
        self.saved = []
        self.deleted = []

    def get(self, request, expire=60):
        del request, expire
        return None

    async def async_get(self, request, expire=60):
        return self.get(request, expire)

    def save(self, request, response):
        self.saved.append((request, response))

    async def delete(self, request):
        self.deleted.append(request)


class FakeConnector:
    """Return one specification discovery snapshot."""

    async def discover(self, request, use_discover_cache=True):
        del use_discover_cache
        return response_pb2.DiscoverResponse(
            code={"value": 200000},
            service=service_pb2.Service(
                name={"value": request.name},
                namespace={"value": request.namespace},
                revision={"value": "revision-1"},
            ),
            instances=[
                service_pb2.Instance(
                    id={"value": "instance-1"},
                    service={"value": request.name},
                    namespace={"value": request.namespace},
                    host={"value": "127.0.0.1"},
                    port={"value": 8080},
                    weight={"value": 100},
                    healthy={"value": True},
                )
            ],
        )


class FakeEngine:
    def __init__(self) -> None:
        self.file_cache = FakeFileCache()
        self.svc_connector = FakeConnector()
        self.update_task_set = {}
        self.stopped = []

    async def stop_service_update(self, service_key, cache_obj):
        assert cache_obj.invalid
        self.update_task_set.pop(service_key, None)
        self.stopped.append(service_key)


def make_cache() -> tuple[LocalCache, FakeEngine]:
    config = Configuration()
    config.set_default()
    value_context = new_value_context()
    engine = FakeEngine()
    value_context.set_value(ContextKeyEngine, engine)
    return LocalCache(InitContext(config=config, value_ctx=value_context)), engine


def test_get_none_instance():
    cache, _ = make_cache()
    si = cache.get_instances(InstanceFilter("Test", "missing", True))
    assert si is None


@pytest.mark.asyncio
async def test_load_instance():
    cache, engine = make_cache()
    await cache.load_instances("svc", "Test")
    si = cache.get_instances(InstanceFilter("Test", "svc", True))
    assert si is not None
    assert [node.get_host() for node in si.get_instances()] == ["127.0.0.1"]
    assert si.get_revision() == "revision-1"
    assert len(engine.file_cache.saved) == 1


@pytest.mark.asyncio
async def test_update_instance():
    cache, _ = make_cache()
    await cache.load_instances("svc", "Test")
    cache.update_instances(ServiceUpdateRequest("Test", "svc"))


@pytest.mark.asyncio
async def test_get_services():
    cache, _ = make_cache()
    services = cache.get_services()
    assert len(services) == 0
    await cache.load_instances("svc", "Test")
    services = cache.get_services()
    assert len(services) == 1


def test_file_cache_round_trips_specification_response(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cache = filecache.LocalFileCache()
    request = InstanceDiscoverRequest(1, "svc", "ns")
    response = response_pb2.DiscoverResponse(
        code={"value": 200000},
        service=service_pb2.Service(
            name={"value": "svc"},
            namespace={"value": "ns"},
            revision={"value": "revision-1"},
        ),
    )

    try:
        assert cache.base_dir == "./polaris/backup"
        assert (tmp_path / "polaris" / "backup").is_dir()
        cache.save(request, response)
        cache.queue.join()
        loaded = cache.get(request)
        assert loaded == response
        cache_file = tmp_path / "polaris" / "backup" / "svc#ns#svc#instance.json"
        assert os.path.abspath(cache.get_cache_file_path(request)) == str(cache_file)
        raw_json = cache_file.read_text(encoding="utf-8")
        assert json.loads(raw_json)["service"]["revision"] == "revision-1"
        assert '"name": "svc"' in raw_json
    finally:
        cache.destroy()
    assert not cache.write_thread.is_alive()
    assert cache.lock_file.closed


def test_file_cache_names_match_instance_files(tmp_path):
    from polaris.pkg.model.error import SDKError

    cache = filecache.LocalFileCache(base_dir=str(tmp_path))
    try:
        name = os.path.basename(
            cache.get_cache_file_path(InstanceDiscoverRequest(1, "svc/name", "ns space"))
        )
        assert name == "svc#ns+space#svc%2Fname#instance.json"
        with pytest.raises(SDKError, match="unsupported discover request type"):
            cache.get_cache_file_path(InstanceDiscoverRequest(3, "svc/name", "ns space"))
    finally:
        cache.destroy()


def test_file_cache_destroy_drains_writes_and_is_idempotent(tmp_path):
    cache = filecache.LocalFileCache(base_dir=str(tmp_path))
    request = InstanceDiscoverRequest(1, "svc", "ns")
    response = response_pb2.DiscoverResponse(code={"value": 200000})
    cache.save(request, response)
    response.code.value = 500000
    cache.destroy()
    cache.destroy()
    loaded = json_format.Parse(
        (tmp_path / "svc#ns#svc#instance.json").read_text(encoding="utf-8"),
        response_pb2.DiscoverResponse(),
    )
    assert loaded.code.value == 200000
    assert not cache.write_thread.is_alive()
    assert cache.lock_file.closed


def test_file_cache_rejects_writes_after_destroy(tmp_path):
    from polaris.pkg.model.error import SDKError

    cache = filecache.LocalFileCache(base_dir=str(tmp_path))
    cache.destroy()
    with pytest.raises(SDKError, match="destroyed"):
        cache.save(InstanceDiscoverRequest(1, "svc", "ns"), response_pb2.DiscoverResponse())


def test_file_cache_write_failure_releases_lock_and_allows_shutdown(tmp_path, monkeypatch):
    errors = []
    cache = filecache.LocalFileCache(base_dir=str(tmp_path))
    cache.retry_interval = 0
    monkeypatch.setattr(cache, "logger", type("Logger", (), {
        "error": lambda self, *args: errors.append(args), "warning": lambda self, *args: None,
    })())
    request = InstanceDiscoverRequest(1, "svc", "ns")
    (tmp_path / "svc#ns#svc#instance.json").mkdir()
    cache.save(request, response_pb2.DiscoverResponse())
    cache.destroy()
    assert len(errors) == 1
    assert errors[0][:2] == ("failed to %s cache backup: %s", "write")
    assert not cache.thread_lock.locked()
    assert not cache.write_thread.is_alive()
    assert cache.lock_file.closed


def test_file_cache_read_after_destroy_returns_no_snapshot(tmp_path):
    cache = filecache.LocalFileCache(base_dir=str(tmp_path))
    request = InstanceDiscoverRequest(1, "svc", "ns")
    cache.save(request, response_pb2.DiscoverResponse())
    cache.destroy()
    assert cache.get(request) is None


def test_cache_object_initializes_idle_clock_without_a_read(monkeypatch):
    monkeypatch.setattr(localcache.time, "monotonic", lambda: 123.5)
    assert CacheObject().last_visit_time == 123.5


@pytest.mark.asyncio
async def test_idle_expiry_releases_instances_and_refresh_tasks(monkeypatch):
    cache, engine = make_cache()
    clock = [100.0]
    monkeypatch.setattr(localcache.time, "monotonic", lambda: clock[0])
    cache.config.get_consumer().get_local_cache().service_expire_time = 5000
    await cache.load_instances("svc", "ns")
    await cache.load_instances("other", "ns")
    keys = set(cache.service_map)
    assert all(obj.last_visit_time == 100 for obj in cache.service_map.values())
    clock[0] = 104.999
    assert await cache.expire_services() == []
    clock[0] = 105.0
    assert set(await cache.expire_services()) == keys
    assert cache.service_map == cache.get_services() == engine.update_task_set == {}
    assert set(engine.stopped) == keys
    assert await cache.expire_services() == []


@pytest.mark.asyncio
async def test_external_instance_read_renews_idle_clock_but_internal_read_does_not(monkeypatch):
    cache, engine = make_cache()
    clock = [100.0]
    monkeypatch.setattr(localcache.time, "monotonic", lambda: clock[0])
    cache.config.get_consumer().get_local_cache().service_expire_time = 5000
    await cache.load_instances("svc", "ns")
    key = ServiceEventKey("ns", "svc", EventType.Instance)
    clock[0] = 104.0
    cache.get_instances(InstanceFilter("ns", "svc", False))
    assert cache.service_map[key].last_visit_time == 104
    clock[0] = 108.0
    cache.get_instances(InstanceFilter("ns", "svc", True))
    cache.get_service_revision("svc", "ns", EventType.Instance)
    assert cache.service_map[key].last_visit_time == 104
    assert await cache.expire_services() == []
    clock[0] = 109.0
    assert await cache.expire_services() == [key]
    assert engine.stopped == [key]


@pytest.mark.asyncio
async def test_expiry_preserves_system_resources_and_same_service_in_other_namespace(monkeypatch):
    cache, engine = make_cache()
    clock = [100.0]
    monkeypatch.setattr(localcache.time, "monotonic", lambda: clock[0])
    cache.config.get_consumer().get_local_cache().service_expire_time = 5000
    await cache.load_instances("polaris.monitor", "Polaris")
    await cache.load_instances("polaris.monitor", "ns")
    clock[0] = 105.0
    key = ServiceEventKey("ns", "polaris.monitor", EventType.Instance)
    assert await cache.expire_services() == [key]
    assert engine.stopped == [key]
    assert set(cache.service_map) == {
        ServiceEventKey("Polaris", "polaris.monitor", EventType.Instance),
    }


@pytest.mark.asyncio
async def test_initial_load_is_not_evicted_while_request_is_in_flight(monkeypatch):
    cache, engine = make_cache()
    clock = [100.0]
    monkeypatch.setattr(localcache.time, "monotonic", lambda: clock[0])
    cache.config.get_consumer().get_local_cache().service_expire_time = 5000
    started, release = asyncio.Event(), asyncio.Event()
    original_discover = engine.svc_connector.discover

    async def discover(request, use_discover_cache=True):
        started.set()
        await release.wait()
        return await original_discover(request, use_discover_cache)

    engine.svc_connector.discover = discover
    loading = asyncio.create_task(cache.load_instances("svc", "ns"))
    await started.wait()
    clock[0] = 110.0
    assert await cache.expire_services() == []
    release.set()
    await loading
    key = ServiceEventKey("ns", "svc", EventType.Instance)
    assert cache.service_map[key].last_visit_time == 110
    assert engine.stopped == []


@pytest.mark.asyncio
async def test_concurrent_initial_loads_share_one_resource_and_request():
    cache, engine = make_cache()
    started, release = asyncio.Event(), asyncio.Event()
    original_discover = engine.svc_connector.discover
    calls = []

    async def discover(request, use_discover_cache=True):
        calls.append(request)
        started.set()
        await release.wait()
        return await original_discover(request, use_discover_cache)

    engine.svc_connector.discover = discover
    first = asyncio.create_task(cache.load_instances("svc", "ns"))
    await started.wait()
    second = asyncio.create_task(cache.load_instances("svc", "ns"))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)
    assert len(calls) == len(cache.service_map) == len(engine.update_task_set) == 1


@pytest.mark.asyncio
async def test_reload_waits_until_eviction_stops_the_old_generation(monkeypatch):
    cache, engine = make_cache()
    cache.config.get_consumer().get_local_cache().service_expire_time = 5000
    await cache.load_instances("svc", "ns")
    key = ServiceEventKey("ns", "svc", EventType.Instance)
    old = cache.service_map[key]
    old.last_visit_time -= 10
    started, release = asyncio.Event(), asyncio.Event()
    original_stop = engine.stop_service_update

    async def stop(service_key, cache_obj):
        started.set()
        await release.wait()
        await original_stop(service_key, cache_obj)

    monkeypatch.setattr(engine, "stop_service_update", stop)
    evicting = asyncio.create_task(cache.expire_services())
    await started.wait()
    assert cache.get_instances(InstanceFilter("ns", "svc", False)) is None
    reloading = asyncio.create_task(cache.load_instances("svc", "ns"))
    await asyncio.sleep(0)
    assert not reloading.done()
    release.set()
    assert await evicting == [key]
    await reloading
    assert cache.service_map[key] is not old
    assert not cache.service_map[key].invalid
    assert engine.update_task_set[key].cache_obj is cache.service_map[key]


@pytest.mark.asyncio
async def test_eviction_rechecks_access_after_waiting_for_resource_lock():
    cache, engine = make_cache()
    cache.config.get_consumer().get_local_cache().service_expire_time = 5000
    await cache.load_instances("svc", "ns")
    key = ServiceEventKey("ns", "svc", EventType.Instance)
    obj = cache.service_map[key]
    obj.last_visit_time -= 10
    await obj.load_lock.acquire()
    evicting = asyncio.create_task(cache.expire_services())
    await asyncio.sleep(0)
    cache.get_instances(InstanceFilter("ns", "svc", False))
    obj.load_lock.release()
    assert await evicting == []
    assert engine.stopped == []


@pytest.mark.asyncio
async def test_failed_initial_load_is_eventually_evicted_without_a_snapshot():
    from polaris.pkg.model.error import ErrorCode, SDKError

    cache, engine = make_cache()
    cache.config.get_consumer().get_local_cache().service_expire_time = 5000

    async def discover(request, use_discover_cache=True):
        raise SDKError(ErrorCode.ErrCodeNetworkError, "offline")

    engine.svc_connector.discover = discover
    with pytest.raises(SDKError):
        await cache.load_instances("svc", "ns")
    key = ServiceEventKey("ns", "svc", EventType.Instance)
    cache.service_map[key].last_visit_time -= 10
    assert await cache.expire_services() == [key]
    assert cache.service_map == engine.update_task_set == {}


@pytest.mark.asyncio
async def test_retry_after_failed_load_keeps_the_tracked_refresh_generation():
    from polaris.pkg.model.error import ErrorCode, SDKError

    cache, engine = make_cache()
    original_discover = engine.svc_connector.discover

    async def discover(request, use_discover_cache=True):
        raise SDKError(ErrorCode.ErrCodeNetworkError, "offline")

    engine.svc_connector.discover = discover
    with pytest.raises(SDKError):
        await cache.load_instances("svc", "ns")
    key = ServiceEventKey("ns", "svc", EventType.Instance)
    task = engine.update_task_set[key]
    engine.svc_connector.discover = original_discover
    await cache.load_instances("svc", "ns")
    assert engine.update_task_set[key] is task
    assert task.cache_obj.value.revision == "revision-1"


@pytest.mark.asyncio
async def test_eviction_continues_to_other_resources_after_cleanup_error(monkeypatch):
    cache, engine = make_cache()
    cache.config.get_consumer().get_local_cache().service_expire_time = 5000
    await cache.load_instances("svc", "ns")
    await cache.load_instances("other", "ns")
    for obj in cache.service_map.values():
        obj.last_visit_time -= 10
    keys = set(cache.service_map)
    original_stop = engine.stop_service_update

    async def stop(service_key, cache_obj):
        await original_stop(service_key, cache_obj)
        if service_key.service == "svc":
            raise OSError("cannot delete backup")

    monkeypatch.setattr(engine, "stop_service_update", stop)
    assert set(await cache.expire_services()) == keys
    assert cache.service_map == engine.update_task_set == {}
    assert set(engine.stopped) == keys


@pytest.mark.asyncio
async def test_file_cache_delete_orders_after_writes_and_before_new_generation(tmp_path, monkeypatch):
    cache = filecache.LocalFileCache(base_dir=str(tmp_path))
    request = InstanceDiscoverRequest(1, "svc", "ns")
    started, release = threading.Event(), threading.Event()
    original_save = cache._save

    def save(service, response):
        if response.code.value == 200000:
            started.set()
            assert release.wait(3)
        original_save(service, response)

    monkeypatch.setattr(cache, "_save", save)
    try:
        cache.save(request, response_pb2.DiscoverResponse(code={"value": 200000}))
        assert await asyncio.to_thread(started.wait, 3)
        pending = asyncio.create_task(cache.delete(request))
        await asyncio.sleep(0)
        assert not pending.done()
        release.set()
        await asyncio.wait_for(pending, 3)
        assert not (tmp_path / "svc#ns#svc#instance.json").exists()
        await cache.delete(request)
        cache.save(request, response_pb2.DiscoverResponse(code={"value": 200001}))
        await asyncio.to_thread(cache.queue.join)
        assert cache.get(request).code.value == 200001
    finally:
        release.set()
        cache.destroy()


@pytest.mark.asyncio
async def test_file_cache_delete_failure_releases_lock_and_reports_error(tmp_path):
    cache = filecache.LocalFileCache(base_dir=str(tmp_path))
    cache.retry_interval = 0
    request = InstanceDiscoverRequest(1, "svc", "ns")
    (tmp_path / "svc#ns#svc#instance.json").mkdir()
    try:
        with pytest.raises(OSError):
            await cache.delete(request)
        assert not cache.thread_lock.locked()
        await cache.delete(InstanceDiscoverRequest(1, "missing", "ns"))
    finally:
        cache.destroy()
    assert not cache.write_thread.is_alive()


@pytest.mark.asyncio
async def test_cancelled_delete_is_still_drained_on_destroy(tmp_path, monkeypatch):
    cache = filecache.LocalFileCache(base_dir=str(tmp_path))
    request = InstanceDiscoverRequest(1, "svc", "ns")
    started, release = threading.Event(), threading.Event()
    original_save = cache._save

    def save(service, response):
        started.set()
        assert release.wait(3)
        original_save(service, response)

    monkeypatch.setattr(cache, "_save", save)
    try:
        cache.save(request, response_pb2.DiscoverResponse(code={"value": 200000}))
        assert await asyncio.to_thread(started.wait, 3)
        pending = asyncio.create_task(cache.delete(request))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    finally:
        release.set()
        cache.destroy()
    assert not (tmp_path / "svc#ns#svc#instance.json").exists()
    assert cache.queue.unfinished_tasks == 0


@pytest.mark.asyncio
async def test_file_cache_rejects_delete_after_destroy(tmp_path):
    from polaris.pkg.model.error import SDKError

    cache = filecache.LocalFileCache(base_dir=str(tmp_path))
    cache.destroy()
    with pytest.raises(SDKError, match="destroyed"):
        await cache.delete(InstanceDiscoverRequest(1, "svc", "ns"))


def new_file_cache(tmp_path, write_retry=2, read_retry=2, interval=7):
    config = Configuration()
    config.set_default()
    options = config.get_consumer().get_local_cache()
    options.persist_dir = str(tmp_path)
    options.persist_max_write_retry = write_retry
    options.persist_max_read_retry = read_retry
    options.persist_retry_interval = interval
    return filecache.LocalFileCache(InitContext(config=config))


def test_file_cache_uses_configured_retry_options(tmp_path):
    cache = new_file_cache(tmp_path, write_retry=3, read_retry=4, interval=25)
    try:
        assert (cache.max_write_retry, cache.max_read_retry, cache.retry_interval) == (3, 4, 0.025)
    finally:
        cache.destroy()


@pytest.mark.parametrize("failures", [1, 2, 3])
def test_file_cache_write_retries_exact_budget_and_releases_lock(tmp_path, monkeypatch, failures):
    cache = new_file_cache(tmp_path)
    request = InstanceDiscoverRequest(1, "svc", "ns")
    response = response_pb2.DiscoverResponse(code={"value": 200000})
    original = os.replace
    attempts, sleeps = [], []

    def replace(source, target):
        attempts.append(source)
        if len(attempts) <= failures:
            raise OSError("temporary rename failure")
        original(source, target)

    def sleep(delay):
        assert not cache.thread_lock.locked()
        sleeps.append(delay)

    monkeypatch.setattr(filecache.os, "replace", replace)
    monkeypatch.setattr(filecache.time, "sleep", sleep)
    try:
        cache.save(request, response)
        cache.queue.join()
        assert len(attempts) == min(failures + 1, 3)
        assert sleeps == [0.007] * min(failures, 2)
        assert cache.get(request) == (response if failures <= 2 else None)
        assert not list(tmp_path.glob("*.tmp"))
        assert not cache.thread_lock.locked()
    finally:
        cache.destroy()


@pytest.mark.parametrize("failure", ["sync", "replace"])
def test_failed_atomic_write_preserves_last_complete_snapshot(tmp_path, monkeypatch, failure):
    cache = new_file_cache(tmp_path, interval=0)
    request = InstanceDiscoverRequest(1, "svc", "ns")
    previous = response_pb2.DiscoverResponse(code={"value": 200000}, info={"value": "last good snapshot"})
    try:
        cache.save(request, previous)
        cache.queue.join()

        def fail(*args):
            raise OSError("interrupted write")

        monkeypatch.setattr(filecache.os, "fsync" if failure == "sync" else "replace", fail)
        cache.save(request, response_pb2.DiscoverResponse(code={"value": 500000}))
        cache.queue.join()
        assert cache.get(request) == previous
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        cache.destroy()


@pytest.mark.parametrize("failure", ["io", "decode", "busy"])
def test_file_cache_read_retries_transient_failures_outside_lock(tmp_path, monkeypatch, failure):
    cache = new_file_cache(tmp_path)
    request = InstanceDiscoverRequest(1, "svc", "ns")
    expected = response_pb2.DiscoverResponse(code={"value": 200000})
    original_read = cache._read
    attempts, waits = [], []

    def read(service, expire):
        attempts.append(service)
        if len(attempts) == 1:
            if failure == "decode":
                (tmp_path / "svc#ns#svc#instance.json").write_bytes(b"\x80")
                return original_read(service, expire)
            raise (BlockingIOError if failure == "busy" else OSError)("temporary read failure")
        return original_read(service, expire)

    def wait(delay):
        assert not cache.thread_lock.locked()
        waits.append(delay)
        (tmp_path / "svc#ns#svc#instance.json").write_text(
            json_format.MessageToJson(expected),
            encoding="utf-8",
        )
        return False

    monkeypatch.setattr(cache, "_read", read)
    monkeypatch.setattr(cache._closing, "wait", wait)
    try:
        assert cache.get(request) == expected
        assert len(attempts) == 2
        assert waits == [0.007]
    finally:
        cache.destroy()


@pytest.mark.parametrize("contents", [b"\x80", b""])
def test_file_cache_unreadable_backup_exhausts_retries(tmp_path, monkeypatch, contents):
    cache = new_file_cache(tmp_path)
    request = InstanceDiscoverRequest(1, "svc", "ns")
    (tmp_path / "svc#ns#svc#instance.json").write_bytes(contents)
    waits = []
    monkeypatch.setattr(cache._closing, "wait", lambda delay: waits.append(delay) or False)
    try:
        assert cache.get(request) is None
        assert waits == [0.007, 0.007]
        assert not cache.thread_lock.locked()
    finally:
        cache.destroy()


def test_file_cache_missing_and_expired_backups_do_not_retry(tmp_path, monkeypatch):
    cache = new_file_cache(tmp_path)
    request = InstanceDiscoverRequest(1, "svc", "ns")
    monkeypatch.setattr(cache._closing, "wait", lambda delay: pytest.fail("cache miss must not retry"))
    try:
        assert cache.get(request) is None
        cache.save(request, response_pb2.DiscoverResponse(code={"value": 200000}))
        cache.queue.join()
        os.utime(tmp_path / "svc#ns#svc#instance.json", (time.time() - 61, time.time() - 61))
        assert cache.get(request) is None
        assert cache.get(request, expire=86400) is not None
    finally:
        cache.destroy()


@pytest.mark.asyncio
async def test_file_cache_delete_uses_write_retry_budget(tmp_path, monkeypatch):
    cache = new_file_cache(tmp_path, interval=0)
    request = InstanceDiscoverRequest(1, "svc", "ns")
    original = cache._delete
    attempts = []

    def delete(service):
        attempts.append(service)
        if len(attempts) < 3:
            raise OSError("temporary delete failure")
        original(service)

    monkeypatch.setattr(cache, "_delete", delete)
    try:
        cache.save(request, response_pb2.DiscoverResponse(code={"value": 200000}))
        await cache.delete(request)
        assert len(attempts) == 3
        assert not (tmp_path / "svc#ns#svc#instance.json").exists()
    finally:
        cache.destroy()


def test_file_cache_destroy_interrupts_reader_retry_delay(tmp_path):
    cache = new_file_cache(tmp_path, interval=60000)
    request = InstanceDiscoverRequest(1, "svc", "ns")
    (tmp_path / "svc#ns#svc#instance.json").write_bytes(b"\x80")
    result = []
    reader = threading.Thread(target=lambda: result.append(cache.get(request)))
    reader.start()
    try:
        cache.destroy()
        reader.join(timeout=2)
        assert not reader.is_alive()
        assert result == [None]
    finally:
        cache.destroy()


@pytest.mark.asyncio
async def test_async_file_read_does_not_block_owner_loop_and_destroy_stops_reader(tmp_path, monkeypatch):
    cache = new_file_cache(tmp_path, interval=60000)
    request = InstanceDiscoverRequest(1, "svc", "ns")
    (tmp_path / "svc#ns#svc#instance.json").write_bytes(b"\x80")
    waiting = threading.Event()
    original = cache._closing.wait

    def wait(delay):
        waiting.set()
        return original(delay)

    monkeypatch.setattr(cache._closing, "wait", wait)
    pending = asyncio.create_task(cache.async_get(request))
    try:
        assert await asyncio.to_thread(waiting.wait, 2)
        assert not pending.done()
        await asyncio.wait_for(asyncio.sleep(0.01), 0.5)
        cache.destroy()
        assert await pending is None
        assert all(not thread.is_alive() for thread in cache._read_executor._threads)
        assert cache.lock_file.closed
        assert await cache.async_get(request) is None
    finally:
        cache.destroy()


def test_file_cache_retries_actual_write_lock_contention(tmp_path, monkeypatch):
    cache = new_file_cache(tmp_path)
    request = InstanceDiscoverRequest(1, "svc", "ns")
    response = response_pb2.DiscoverResponse(code={"value": 200000})
    waits = []
    cache.thread_lock.acquire()

    def sleep(delay):
        waits.append(delay)
        cache.thread_lock.release()

    monkeypatch.setattr(filecache.time, "sleep", sleep)
    try:
        cache.save(request, response)
        cache.queue.join()
        assert waits == [0.007]
        assert cache.get(request) == response
    finally:
        cache.destroy()


def test_file_cache_destroy_drains_retry_budget_exceeding_old_shutdown_limit(tmp_path, monkeypatch):
    cache = new_file_cache(tmp_path, write_retry=1, interval=5500)
    request = InstanceDiscoverRequest(1, "svc", "ns")
    attempts = []
    original = cache._save

    def save(service, response):
        attempts.append(service)
        if len(attempts) == 1:
            raise OSError("temporary failure during shutdown")
        original(service, response)

    monkeypatch.setattr(cache, "_save", save)
    cache.save(request, response_pb2.DiscoverResponse(code={"value": 200000}))
    cache.destroy()
    assert len(attempts) == 2
    assert not cache.write_thread.is_alive()
    assert cache.lock_file.closed
    assert cache.queue.unfinished_tasks == 0
    assert (tmp_path / "svc#ns#svc#instance.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["code", "type", "name", "namespace", "empty"])
async def test_registry_rejects_mismatched_or_incomplete_backup(tmp_path, invalid):
    cache, engine = make_cache()
    disk = new_file_cache(tmp_path, interval=0)
    engine.file_cache = disk
    request = InstanceDiscoverRequest(1, "svc", "ns")
    response = await FakeConnector().discover(request)
    if invalid == "code":
        response.code.value = 500000
    elif invalid == "type":
        response.type = 3
    elif invalid == "empty":
        response.Clear()
    else:
        getattr(response.service, invalid).value = "other"
    try:
        disk.save(request, response)
        disk.queue.join()
        assert await localcache.load_file_cache(engine, request) is None
    finally:
        disk.destroy()


@pytest.mark.asyncio
@pytest.mark.parametrize("age", [0, 86401])
async def test_disk_snapshot_stays_hidden_until_remote_update(tmp_path, age):
    from polaris.pkg.model.error import ErrorCode, SDKError

    cache, engine = make_cache()
    disk = new_file_cache(tmp_path, interval=0)
    engine.file_cache = disk
    cache.config.get_global().get_api().timeout = 30
    calls = []

    async def discover(request, use_discover_cache=True):
        calls.append(request.type)
        await asyncio.Event().wait()

    engine.svc_connector.discover = discover
    request = InstanceDiscoverRequest(1, "svc", "ns")
    try:
        disk.save(request, await FakeConnector().discover(request))
        disk.queue.join()
        os.utime(tmp_path / "svc#ns#svc#instance.json", (time.time() - age, time.time() - age))
        with pytest.raises(SDKError, match="Timed out") as error:
            await asyncio.wait_for(cache.load_instances("svc", "ns"), 1)
        key = ServiceEventKey("ns", "svc", EventType.Instance)
        cached = cache.service_map[key]
        assert error.value.err_code == ErrorCode.ErrCodeAPITimeoutError
        assert calls == [1]
        assert not cached.loading
        assert cached.is_remote_updated() is False
        assert cached.value.get_revision() == "revision-1"
        assert cache.get_instances(InstanceFilter("ns", "svc", False)) is None
        assert cache.get_instances(InstanceFilter("ns", "svc", True)) is None
    finally:
        disk.destroy()


@pytest.mark.asyncio
async def test_missing_backup_still_waits_for_remote(tmp_path):
    from polaris.pkg.model.error import ErrorCode, SDKError

    cache, engine = make_cache()
    disk = new_file_cache(tmp_path, interval=0)
    engine.file_cache = disk
    cache.config.get_global().get_api().timeout = 30

    async def discover(request, use_discover_cache=True):
        await asyncio.Event().wait()

    engine.svc_connector.discover = discover
    try:
        with pytest.raises(SDKError, match="Timed out") as error:
            await asyncio.wait_for(cache.load_instances("svc", "ns"), 1)
        cached = next(iter(cache.service_map.values()))
        assert error.value.err_code == ErrorCode.ErrCodeAPITimeoutError
        assert cached.value is None
        assert cached.is_remote_updated() is False
        assert not cached.loading
    finally:
        disk.destroy()


@pytest.mark.asyncio
async def test_remote_failure_does_not_publish_old_backup(tmp_path):
    from polaris.pkg.model.error import ErrorCode, SDKError

    cache, engine = make_cache()
    disk = new_file_cache(tmp_path, interval=0)
    engine.file_cache = disk
    request = InstanceDiscoverRequest(1, "svc", "ns")

    async def discover(request, use_discover_cache=True):
        raise SDKError(ErrorCode.ErrCodeNetworkError, "offline")

    engine.svc_connector.discover = discover
    try:
        disk.save(request, await FakeConnector().discover(request))
        disk.queue.join()
        os.utime(tmp_path / "svc#ns#svc#instance.json", (time.time() - 86401, time.time() - 86401))
        with pytest.raises(SDKError):
            await cache.load_instances("svc", "ns")
        cached = cache.service_map[ServiceEventKey("ns", "svc", EventType.Instance)]
        assert cached.is_remote_updated() is False
        assert cached.value.get_revision() == "revision-1"
        assert cache.get_instances(InstanceFilter("ns", "svc", False)) is None
    finally:
        disk.destroy()


@pytest.mark.asyncio
async def test_remote_update_publishes_instances_regardless_of_backup_age(tmp_path):
    cache, engine = make_cache()
    disk = new_file_cache(tmp_path, interval=0)
    engine.file_cache = disk
    request = InstanceDiscoverRequest(1, "svc", "ns")

    async def discover(request, use_discover_cache=True):
        response = await FakeConnector().discover(request)
        response.service.revision.value = "revision-remote"
        return response

    engine.svc_connector.discover = discover
    try:
        disk.save(request, await FakeConnector().discover(request))
        disk.queue.join()
        os.utime(tmp_path / "svc#ns#svc#instance.json", (time.time() - 86401, time.time() - 86401))
        await cache.load_instances("svc", "ns")
        key = ServiceEventKey("ns", "svc", EventType.Instance)
        assert cache.service_map[key].is_remote_updated() is True
        assert cache.get_instances(InstanceFilter("ns", "svc", False)).get_revision() == "revision-remote"
    finally:
        disk.destroy()
