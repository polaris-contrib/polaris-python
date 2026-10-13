"""Local discovery cache with optional per-resource disk persistence."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Iterable
from urllib.parse import quote

from google.protobuf.message import DecodeError
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

from polaris_python.core.log import CACHE_LOGGER

try:
    import fcntl
except ImportError:  # Windows: backups are written without a cross-process lock.
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(CACHE_LOGGER)

INSTANCE = response_pb2.DiscoverResponse.INSTANCE
_TYPE_NAMES = {
    value.number: value.name
    for value in response_pb2.DiscoverResponse.DESCRIPTOR.enum_types_by_name["DiscoverResponseType"].values
}
_ResourceKey = tuple[str, str, int]


@dataclass(frozen=True, slots=True)
class CachedResource:
    """One discovery snapshot held by the local registry.

    ``from_file`` marks a snapshot restored from disk. It is served only while
    the server has not answered, and any server snapshot replaces it.
    """

    response: response_pb2.DiscoverResponse
    revision: str
    from_file: bool = False
    updated_at: float = 0.0


class LocalRegistry(ABC):
    """Cache contract used by the consumer side of the SDK.

    Snapshots are keyed by namespace, service and discover type, like the
    cache objects of polaris-java ``InMemoryRegistry``.
    """

    @abstractmethod
    async def get_resource(self, namespace: str, service: str, discover_type: int) -> CachedResource | None:
        """Return the cached snapshot for one resource, if any."""

    @abstractmethod
    async def put_resource(
        self,
        namespace: str,
        service: str,
        discover_type: int,
        response: response_pb2.DiscoverResponse,
    ) -> bool:
        """Store a server snapshot and return whether it replaced different data."""

    @abstractmethod
    async def remove_resource(self, namespace: str, service: str, discover_type: int) -> None:
        """Drop one resource from memory and from any persisted copy."""

    async def restore_resource(self, namespace: str, service: str, discover_type: int) -> CachedResource | None:
        """Load a persisted snapshot when nothing is cached; memory-only caches return ``None``."""
        return None

    async def get_instances(self, namespace: str, service: str) -> list[service_pb2.Instance]:
        """Return a copy of cached instances for one service."""
        resource = await self.get_resource(namespace, service, INSTANCE)
        if resource is None:
            return []
        return [_copy_instance(instance) for instance in resource.response.instances]

    async def put_instances(
        self, namespace: str, service: str, instances: Iterable[service_pb2.Instance]
    ) -> None:
        """Replace the cached instance snapshot for one service."""
        response = response_pb2.DiscoverResponse(type=INSTANCE, instances=list(instances))
        await self.put_resource(namespace, service, INSTANCE, response)

    async def remove_instances(self, namespace: str, service: str) -> None:
        """Remove one service's instance snapshot from the cache."""
        await self.remove_resource(namespace, service, INSTANCE)

    async def close(self) -> None:
        """Flush and close the cache when the context is destroyed."""


class InMemoryRegistry(LocalRegistry):
    """Process-local cache. Snapshots are lost when the process exits."""

    def __init__(self) -> None:
        self._resources: dict[_ResourceKey, CachedResource] = {}
        self._lock = RLock()

    async def get_resource(self, namespace: str, service: str, discover_type: int) -> CachedResource | None:
        with self._lock:
            return self._resources.get(_key(namespace, service, discover_type))

    async def put_resource(
        self,
        namespace: str,
        service: str,
        discover_type: int,
        response: response_pb2.DiscoverResponse,
    ) -> bool:
        return self._replace(_key(namespace, service, discover_type), _snapshot(response))

    async def remove_resource(self, namespace: str, service: str, discover_type: int) -> None:
        with self._lock:
            self._resources.pop(_key(namespace, service, discover_type), None)

    def _replace(self, key: _ResourceKey, resource: CachedResource) -> bool:
        with self._lock:
            changed = _differs(self._resources.get(key), resource)
            if changed:
                self._resources[key] = resource
            return changed

    def _insert_if_absent(self, key: _ResourceKey, resource: CachedResource) -> bool:
        with self._lock:
            if key in self._resources:
                return False
            self._resources[key] = resource
            return True


class PersistentRegistry(InMemoryRegistry):
    """In-memory cache that backs up each changed snapshot to ``persist_dir``.

    Mirrors polaris-java ``MessagePersistHandler``: one file per resource
    (``svc#<namespace>#<service>#<type>.json``). A single background worker
    writes, deletes and reads the files in submission order, so discovery
    never waits for the disk. Each write holds ``<file>.lock`` and moves a
    temporary file into place, and is retried ``max_write_retry`` times.
    Files are read back only through ``restore_resource``, when the server
    cannot provide a snapshot.
    """

    def __init__(
        self,
        persist_dir: str | Path,
        *,
        max_write_retry: int = 1,
        max_read_retry: int = 0,
        retry_interval_seconds: float = 0.5,
    ) -> None:
        super().__init__()
        self.persist_dir = Path(persist_dir).expanduser()
        self._max_write_retry = max_write_retry
        self._max_read_retry = max_read_retry
        self._retry_interval = retry_interval_seconds
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="polaris-persist")
        self._closed = False

    async def put_resource(
        self,
        namespace: str,
        service: str,
        discover_type: int,
        response: response_pb2.DiscoverResponse,
    ) -> bool:
        key = _key(namespace, service, discover_type)
        resource = _snapshot(response)
        changed = self._replace(key, resource)
        if changed:
            self._submit(self._save, key, resource)
        return changed

    async def remove_resource(self, namespace: str, service: str, discover_type: int) -> None:
        await super().remove_resource(namespace, service, discover_type)
        self._submit(self._delete, _key(namespace, service, discover_type))

    async def restore_resource(self, namespace: str, service: str, discover_type: int) -> CachedResource | None:
        key = _key(namespace, service, discover_type)
        if self._closed or await self.get_resource(namespace, service, discover_type) is not None:
            return None
        resource = await asyncio.wrap_future(self._worker.submit(self._load, key))
        if resource is None or not self._insert_if_absent(key, resource):
            return None
        return resource

    async def flush(self) -> None:
        """Wait until every queued write and delete has reached the disk."""
        if not self._closed:
            await asyncio.wrap_future(self._worker.submit(_noop))

    async def close(self) -> None:
        """Finish queued disk work and stop the background worker."""
        if self._closed:
            return
        self._closed = True
        await asyncio.to_thread(self._worker.shutdown, wait=True)

    def path_for(self, namespace: str, service: str, discover_type: int) -> Path:
        """Return the snapshot file used for one resource."""
        type_name = _TYPE_NAMES.get(int(discover_type), str(int(discover_type))).lower()
        return self.persist_dir / f"svc#{quote(namespace, safe='')}#{quote(service, safe='')}#{type_name}.json"

    def _submit(self, task: Callable[..., None], *args: Any) -> None:
        if self._closed:
            return
        try:
            future = self._worker.submit(task, *args)
        except RuntimeError:
            return
        future.add_done_callback(_log_worker_failure)

    def _save(self, key: _ResourceKey, resource: CachedResource) -> None:
        path = self.path_for(*key)
        payload = json.dumps(
            {
                "version": 1,
                "namespace": key[0],
                "service": key[1],
                "type": _TYPE_NAMES.get(key[2], str(key[2])),
                "revision": resource.revision,
                "saved_at": resource.updated_at,
                "response": base64.b64encode(resource.response.SerializeToString()).decode("ascii"),
            },
            sort_keys=True,
        )
        attempts = self._max_write_retry + 1
        error: OSError | None = None
        for attempt in range(attempts):
            if attempt:
                time.sleep(self._retry_interval)
            temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            try:
                self.persist_dir.mkdir(parents=True, exist_ok=True)
                with _file_lock(_lock_path(path)):
                    temporary.write_text(payload, encoding="utf-8")
                    temporary.replace(path)
                logger.debug("persisted %s revision %r to %s", _TYPE_NAMES.get(key[2]), resource.revision, path)
                return
            except OSError as exc:
                error = exc
                temporary.unlink(missing_ok=True)
        logger.warning("could not persist Polaris cache %s after %d attempts: %s", path, attempts, error)

    def _load(self, key: _ResourceKey) -> CachedResource | None:
        path = self.path_for(*key)
        error: Exception | None = None
        for attempt in range(self._max_read_retry + 1):
            if attempt:
                time.sleep(self._retry_interval)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                response = response_pb2.DiscoverResponse()
                response.ParseFromString(base64.b64decode(payload["response"]))
                return CachedResource(
                    response,
                    str(payload.get("revision", "")),
                    from_file=True,
                    updated_at=float(payload.get("saved_at", 0.0)),
                )
            except FileNotFoundError:
                return None
            except (OSError, ValueError, KeyError, TypeError, DecodeError) as exc:
                error = exc
        logger.warning("could not read Polaris cache %s: %s", path, error)
        return None

    def _delete(self, key: _ResourceKey) -> None:
        path = self.path_for(*key)
        for target in (path, _lock_path(path)):
            try:
                target.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("could not delete Polaris cache %s: %s", target, exc)


def _key(namespace: str, service: str, discover_type: int) -> _ResourceKey:
    return (namespace, service, int(discover_type))


def _lock_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive, non-blocking lock on ``path``; raise ``OSError`` when another process holds it."""
    with path.open("a+b") as handle:
        if fcntl is None:
            yield
            return
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _noop() -> None:
    return None


def _log_worker_failure(future: Future[None]) -> None:
    if not future.cancelled() and future.exception() is not None:
        logger.error("Polaris cache disk task failed", exc_info=future.exception())


def _snapshot(response: response_pb2.DiscoverResponse) -> CachedResource:
    copied = response_pb2.DiscoverResponse()
    copied.CopyFrom(response)
    return CachedResource(copied, copied.service.revision.value, updated_at=time.time())


def _differs(old: CachedResource | None, new: CachedResource) -> bool:
    """Return whether ``new`` replaces ``old``.

    Restored snapshots always yield to server data. Otherwise the revision
    decides, and the content decides when the server sends no revision.
    """
    if old is None or old.from_file:
        return True
    if new.revision:
        return old.revision != new.revision
    return old.response != new.response


def _copy_instance(instance: service_pb2.Instance) -> service_pb2.Instance:
    copied = service_pb2.Instance()
    copied.CopyFrom(instance)
    return copied


FileLocalRegistry = PersistentRegistry
MemoryLocalRegistry = InMemoryRegistry
