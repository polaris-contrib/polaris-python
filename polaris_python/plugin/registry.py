"""Local discovery cache implementations."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from threading import RLock
from typing import Iterable

from polarismesh_specification.api.v1.service_manage import service_pb2

logger = logging.getLogger(__name__)


class LocalRegistry(ABC):
    """Cache contract used by the consumer side of the SDK."""

    @abstractmethod
    async def get_instances(self, namespace: str, service: str) -> list[service_pb2.Instance]:
        """Return a copy of cached instances for one service."""

    @abstractmethod
    async def put_instances(
        self, namespace: str, service: str, instances: Iterable[service_pb2.Instance]
    ) -> None:
        """Replace the cached snapshot for one service."""

    @abstractmethod
    async def remove_instances(self, namespace: str, service: str) -> None:
        """Remove one service snapshot from the cache."""

    async def close(self) -> None:
        """Flush and close the cache when the context is destroyed."""


class InMemoryRegistry(LocalRegistry):
    """Fast process-local cache, useful for tests and ephemeral clients."""

    def __init__(self) -> None:
        self._instances: dict[tuple[str, str], list[service_pb2.Instance]] = {}
        self._lock = asyncio.Lock()

    async def get_instances(self, namespace: str, service: str) -> list[service_pb2.Instance]:
        async with self._lock:
            return [self._copy(instance) for instance in self._instances.get((namespace, service), [])]

    async def put_instances(
        self, namespace: str, service: str, instances: Iterable[service_pb2.Instance]
    ) -> None:
        async with self._lock:
            self._instances[(namespace, service)] = [self._copy(instance) for instance in instances]

    async def remove_instances(self, namespace: str, service: str) -> None:
        async with self._lock:
            self._instances.pop((namespace, service), None)

    @staticmethod
    def _copy(instance: service_pb2.Instance) -> service_pb2.Instance:
        copied = service_pb2.Instance()
        copied.CopyFrom(instance)
        return copied


class JsonFileRegistry(InMemoryRegistry):
    """In-memory cache backed by an atomic JSON file for restart recovery."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path).expanduser()
        self._file_lock = RLock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            for key, encoded_instances in payload.get("instances", {}).items():
                namespace, service = key.split("\x00", maxsplit=1)
                instances = []
                for encoded in encoded_instances:
                    instance = service_pb2.Instance()
                    instance.ParseFromString(base64.b64decode(encoded))
                    instances.append(instance)
                self._instances[(namespace, service)] = instances
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("could not load Polaris registry cache %s: %s", self.path, exc)

    def _persist(self) -> None:
        payload = {
            "version": 1,
            "instances": {
                "\x00".join(key): [
                    base64.b64encode(instance.SerializeToString()).decode("ascii")
                    for instance in instances
                ]
                for key, instances in self._instances.items()
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary_path.replace(self.path)

    async def put_instances(
        self, namespace: str, service: str, instances: Iterable[service_pb2.Instance]
    ) -> None:
        await super().put_instances(namespace, service, instances)
        with self._file_lock:
            self._persist()

    async def remove_instances(self, namespace: str, service: str) -> None:
        await super().remove_instances(namespace, service)
        with self._file_lock:
            self._persist()


FileLocalRegistry = JsonFileRegistry
MemoryLocalRegistry = InMemoryRegistry
