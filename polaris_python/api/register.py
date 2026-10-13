"""Heartbeat tasks for instances registered through ``ProviderAPI``."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Iterable
from dataclasses import dataclass

from google.protobuf.message import Message
from polarismesh_specification.api.v1.service_manage import service_pb2

from polaris_python.core.config import Config
from polaris_python.core.error import NOT_FOUND_RESOURCE, PolarisResponseError, ensure_success
from polaris_python.core.log import HEARTBEAT_LOGGER
from polaris_python.plugin.connector import ServerConnector

heartbeat_log = logging.getLogger(HEARTBEAT_LOGGER)

DEFAULT_INSTANCE_TTL = 5
_FAILURE_THRESHOLD = 2
_MAX_REREGISTER_DELAY = 60.0
_StateKey = tuple[str, str, str, int]


def prepare_heartbeat(instance: service_pb2.Instance) -> int | None:
    """Return the heartbeat TTL of ``instance``, filling in Java's default of 5 seconds.

    Returns ``None`` when the instance explicitly disables health checks.
    """
    if instance.HasField("enable_health_check") and not instance.enable_health_check.value:
        return None
    heartbeat = instance.health_check.heartbeat
    if heartbeat.ttl.value == 0:
        instance.health_check.type = service_pb2.HealthCheck.HEARTBEAT
        heartbeat.ttl.value = DEFAULT_INSTANCE_TTL
    return int(heartbeat.ttl.value)


def describe(instance: service_pb2.Instance) -> str:
    """Format an instance as ``namespace/service host:port`` for logs."""
    return f"{instance.namespace.value}/{instance.service.value} {instance.host.value}:{instance.port.value}"


@dataclass(slots=True)
class _RegisterState:
    request: service_pb2.Instance
    instance_id: str
    ttl: int
    first_registered: float
    heartbeat_task: asyncio.Task[None] | None = None
    reregister_task: asyncio.Task[None] | None = None
    failures: int = 0
    reregisters: int = 0


class RegisterFlow:
    """Heartbeat registered instances every TTL and register them again when Polaris loses them.

    Mirrors polaris-java ``RegisterFlow`` and ``RegisterStateManager``: one
    state per namespace, service, host and port. Two heartbeats in a row
    answered with ``400202`` (resource not found) schedule a re-registration,
    no earlier than ``min_register_interval_seconds`` after the first
    registration, with exponential back-off capped at 60 seconds.
    """

    def __init__(self, config: Config, connector: ServerConnector) -> None:
        self._config = config
        self._connector = connector
        self._states: dict[_StateKey, _RegisterState] = {}

    def track(self, request: service_pb2.Instance, instance_id: str, ttl: int) -> None:
        """Start heartbeating a registered instance; a repeat registration only refreshes its request."""
        key = _state_key(request)
        state = self._states.get(key)
        if state is not None:
            state.request = request
            state.instance_id = instance_id or state.instance_id
            return
        state = _RegisterState(request, instance_id, ttl, time.monotonic())
        state.heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(state), name=f"polaris-heartbeat-{describe(request)}"
        )
        self._states[key] = state
        heartbeat_log.info("heartbeat task started for %s ttl=%ss", describe(request), ttl)

    async def untrack(self, instance: service_pb2.Instance) -> None:
        """Stop the heartbeat task of one instance, e.g. before deregistering it."""
        state = self._states.pop(_state_key(instance), None)
        if state is not None:
            await _cancel(_tasks(state))
            heartbeat_log.info("heartbeat task stopped for %s", describe(state.request))

    async def close(self) -> None:
        """Stop every heartbeat and pending re-registration."""
        states = list(self._states.values())
        self._states.clear()
        await _cancel(task for state in states for task in _tasks(state))

    async def _heartbeat_loop(self, state: _RegisterState) -> None:
        loop = asyncio.get_running_loop()
        next_beat = loop.time()
        while True:
            next_beat += state.ttl
            await asyncio.sleep(max(0.0, next_beat - loop.time()))
            await self._run_heartbeat(state)

    async def _run_heartbeat(self, state: _RegisterState) -> None:
        """Send one heartbeat, count not-found answers and re-register when they repeat."""
        name = describe(state.request)
        try:
            response = await self._connector.heartbeat(_heartbeat_request(state))
            if isinstance(response, Message):
                ensure_success(response)
        except asyncio.CancelledError:
            raise
        except PolarisResponseError as exc:
            if exc.code == NOT_FOUND_RESOURCE:
                state.failures += 1
            else:
                state.failures = 0
            heartbeat_log.error("heartbeat %s failed: %s (not-found count %d)", name, exc, state.failures)
        except Exception as exc:
            state.failures = 0
            heartbeat_log.error("heartbeat %s failed: %s", name, exc)
        else:
            state.failures = 0
            heartbeat_log.info("heartbeat %s ok", name)
        if state.failures < _FAILURE_THRESHOLD:
            return
        if time.monotonic() - state.first_registered < self._config.min_register_interval_seconds:
            return
        if state.reregister_task is not None and not state.reregister_task.done():
            return
        delay = _reregister_delay(state)
        heartbeat_log.info("re-registering %s in %.1fs (attempt %d)", name, delay, state.reregisters + 1)
        state.reregister_task = asyncio.create_task(self._reregister(state, delay), name=f"polaris-reregister-{name}")
        state.reregisters += 1

    async def _reregister(self, state: _RegisterState, delay: float) -> None:
        await asyncio.sleep(delay)
        name = describe(state.request)
        try:
            response = await self._connector.register_instance(state.request)
            if isinstance(response, Message):
                ensure_success(response)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            heartbeat_log.error("re-register %s failed: %s", name, exc)
            return
        registered = getattr(response, "instance", None)
        if registered is not None and registered.id.value:
            state.instance_id = registered.id.value
        state.failures = 0
        state.reregisters = 0
        heartbeat_log.info("re-registered %s id=%s", name, state.instance_id)


def _state_key(instance: service_pb2.Instance) -> _StateKey:
    return (instance.namespace.value, instance.service.value, instance.host.value, int(instance.port.value))


def _heartbeat_request(state: _RegisterState) -> service_pb2.Instance:
    request = state.request
    heartbeat = service_pb2.Instance(
        service=request.service,
        namespace=request.namespace,
        host=request.host,
        port=request.port,
    )
    if state.instance_id:
        heartbeat.id.value = state.instance_id
    if request.HasField("service_token"):
        heartbeat.service_token.CopyFrom(request.service_token)
    return heartbeat


def _reregister_delay(state: _RegisterState) -> float:
    if state.reregisters == 0:
        return 0.0
    base = state.ttl * 2 ** (state.reregisters - 1)
    return min(base + random.randrange(state.ttl), _MAX_REREGISTER_DELAY)


def _tasks(state: _RegisterState) -> list[asyncio.Task[None]]:
    return [task for task in (state.heartbeat_task, state.reregister_task) if task is not None]


async def _cancel(tasks: Iterable[asyncio.Task[None]]) -> None:
    pending = list(tasks)
    for task in pending:
        task.cancel()
    loop = asyncio.get_running_loop()
    local = [task for task in pending if task.get_loop() is loop]
    if local:
        await asyncio.gather(*local, return_exceptions=True)
