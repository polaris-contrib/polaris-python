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

"""Instance heartbeat scheduling and Java-compatible re-registration."""

from __future__ import annotations

import asyncio
import copy
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from weakref import WeakValueDictionary

import polaris.api.log as logger
from polaris.pkg.model.error import SDKError, ServerCode
from polaris.pkg.model.server import (
    InstanceDeRegisterRequest,
    InstanceHeartbeatRequest,
    InstanceRegisterRequest,
    InstanceRegisterResponse,
)

InstanceKey = tuple[str, str, str, int]


def _instance_key(request: InstanceRegisterRequest | InstanceDeRegisterRequest) -> InstanceKey:
    return request.namespace, request.service, request.host, request.port


@dataclass
class RegisterState:
    """Keep a private request snapshot and the tasks for one registered instance."""

    request: InstanceRegisterRequest
    first_register_time: float
    heartbeat_task: asyncio.Task[None] | None = None
    re_register_task: asyncio.Task[None] | None = None
    heartbeat_fail_count: int = 0
    re_register_count: int = 0
    instance_ids: set[str] = field(default_factory=set)


class RegisterStateManager:
    """Own registration tasks on the SDK loop and cancel them before deregistration."""

    def __init__(
        self,
        register: Callable[[InstanceRegisterRequest], Awaitable[InstanceRegisterResponse]],
        heartbeat: Callable[[InstanceHeartbeatRequest], Awaitable[None]],
        min_register_interval: int,
    ) -> None:
        self._register = register
        self._heartbeat = heartbeat
        self._min_register_interval = min_register_interval / 1000
        self._states: dict[InstanceKey, RegisterState] = {}
        self._locks: WeakValueDictionary[InstanceKey, asyncio.Lock] = WeakValueDictionary()
        self._closed = False

    def _key_for(self, request: InstanceRegisterRequest | InstanceDeRegisterRequest) -> InstanceKey:
        if request.instance_id:
            for key, state in self._states.items():
                if request.instance_id in state.instance_ids:
                    return key
        return _instance_key(request)

    def operation_lock(self, request: InstanceRegisterRequest | InstanceDeRegisterRequest) -> asyncio.Lock:
        """Serialize explicit registration and deregistration for the same instance."""
        key = self._key_for(request)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def put(self, request: InstanceRegisterRequest) -> None:
        """Replace an instance's schedule without creating duplicate heartbeat tasks."""
        previous = self._states.pop(_instance_key(request), None)
        if previous is not None:
            await self._cancel([previous])
        if self._closed:
            return
        state = RegisterState(copy.deepcopy(request), asyncio.get_running_loop().time())
        state.instance_ids.add(request.instance_id)
        self._states[_instance_key(request)] = state
        state.heartbeat_task = asyncio.create_task(self._run_heartbeat(state))

    async def remove(
        self, request: InstanceRegisterRequest | InstanceDeRegisterRequest,
    ) -> InstanceRegisterRequest | None:
        """Cancel heartbeats and pending re-registration by instance ID or address."""
        key = self._key_for(request)
        state = self._states.get(key)
        if state is None:
            return
        # An explicit ID takes precedence over possibly stale address fields.
        if request.instance_id and request.instance_id not in state.instance_ids:
            return
        self._states.pop(key)
        await self._cancel([state])
        return state.request

    async def close(self) -> None:
        """Stop and await all tasks before the SDK closes its connector."""
        self._closed = True
        states = list(self._states.values())
        self._states.clear()
        await self._cancel(states)

    @staticmethod
    async def _cancel(states: list[RegisterState]) -> None:
        tasks = [task for state in states for task in (state.heartbeat_task, state.re_register_task)
                 if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _active(self, state: RegisterState) -> bool:
        return not self._closed and self._states.get(_instance_key(state.request)) is state

    async def _run_heartbeat(self, state: RegisterState) -> None:
        loop = asyncio.get_running_loop()
        interval = state.request.ttl
        next_tick = loop.time() + interval
        while self._active(state):
            await asyncio.sleep(max(0, next_tick - loop.time()))
            if not self._active(state):
                return
            await self._heartbeat_once(state)
            next_tick += interval
            # Skip missed ticks; do not overlap RPCs or burst after a slow request.
            if next_tick < loop.time():
                next_tick = loop.time() + interval

    async def _heartbeat_once(self, state: RegisterState) -> None:
        request = state.request
        heartbeat = InstanceHeartbeatRequest(
            request.service, request.service_token, request.namespace, request.instance_id,
            request.host, request.port,
        )
        try:
            await self._heartbeat(heartbeat)
            state.heartbeat_fail_count = 0
        except Exception as error:
            if isinstance(error, SDKError) and error.server_code == ServerCode.NotFoundResource:
                state.heartbeat_fail_count += 1
            else:
                state.heartbeat_fail_count = 0
            logger.warning("instance heartbeat failed for %s: %s", _instance_key(request), error)

        if (not self._active(state) or state.heartbeat_fail_count < 2
                or asyncio.get_running_loop().time() - state.first_register_time < self._min_register_interval):
            return
        if state.re_register_task is not None and not state.re_register_task.done():
            return
        attempt = state.re_register_count
        delay = 0 if attempt == 0 else min(
            request.ttl * 2 ** min(attempt - 1, 6) + random.randrange(request.ttl), 60,
        )
        state.re_register_count += 1
        state.re_register_task = asyncio.create_task(self._re_register(state, delay))

    async def _re_register(self, state: RegisterState, delay: float) -> None:
        if delay:
            await asyncio.sleep(delay)
        if not self._active(state):
            return
        try:
            response = await self._register(state.request)
            state.request.instance_id = response.instance_id
            state.instance_ids.add(response.instance_id)
            state.heartbeat_fail_count = 0
            state.re_register_count = 0
        except Exception as error:
            logger.warning("instance re-registration failed for %s: %s", _instance_key(state.request), error)
