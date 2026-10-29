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
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Lossless online/offline flow, mirroring the Java lossless plugin suite."""

from __future__ import annotations

import asyncio
import ipaddress
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from aiohttp import ClientSession, ClientTimeout
from aiohttp import web

import polaris.api.log as logger
from polaris.pkg.config.api import Configuration, LosslessConfig
from polaris.pkg.model.lossless import (
    InstanceProperties,
    LosslessActionProvider,
    LosslessInstance,
    RegisterStatus,
)
from polaris.pkg.model.server import InstanceDiscoverRequest
from polaris.pkg.model.service import Instance, ServiceInstances
from polarismesh_specification.api.v1.traffic_manage import lossless_pb2

# DiscoverRequest.DiscoverRequestType.LOSSLESS
DISCOVER_TYPE_LOSSLESS = 103
DELAY_BY_TIME = "DELAY_BY_TIME"
DELAY_BY_HEALTH_CHECK = "DELAY_BY_HEALTH_CHECK"
STRATEGIES = (DELAY_BY_TIME, DELAY_BY_HEALTH_CHECK)
RULE_REFRESH_INTERVAL_SECONDS = 30.0

lossless_logger = logger.get_logger("lossless")


@dataclass
class LosslessOptions:
    """Effective lossless settings, with server rules taking precedence."""

    delay_register_enable: bool
    delay_register_interval_ms: int
    health_check_interval_ms: int
    strategy: str
    health_check_path: str
    warmup_enable: bool
    warmup_interval_second: int
    warmup_curvature: float
    warmup_overload_protection: bool
    warmup_overload_threshold: int
    offline_enable: bool
    readiness_enable: bool


def _submessage(parent, name: str):
    """Return a present proto submessage, or None for missing/default."""
    if parent is None or not parent.HasField(name):
        return None
    return getattr(parent, name)


def _extract_rules(response) -> List:
    rules = list(getattr(response, "losslessRuleList", []) or [])
    if rules:
        return rules
    if getattr(response, "HasField", lambda *_: False)("lossless"):
        return [response.lossless]
    return []


def _match_rule(instance: LosslessInstance, rules: List):
    """Match by metadata when rules define labels, otherwise use the first rule."""
    if not rules:
        return None
    metadata_rules = {}
    for rule in rules:
        metadata = dict(getattr(rule, "metadata", {}) or {})
        for key, value in metadata.items():
            metadata_rules.setdefault(key, {})[value] = rule
    if not metadata_rules:
        return rules[0]
    for key, values in metadata_rules.items():
        matched = values.get(instance.metadata.get(key))
        if matched is not None:
            return matched
    return None


def _options_from_rule(rule, config: LosslessConfig) -> LosslessOptions:
    online = _submessage(rule, "losslessOnline")
    delay = _submessage(online, "delayRegister")
    warmup = _submessage(online, "warmup")
    readiness = _submessage(online, "readiness")
    offline = _submessage(rule, "losslessOffline")
    strategy = config.strategy
    if delay is not None and delay.strategy:
        try:
            strategy = lossless_pb2.DelayRegister.DelayStrategy.Name(delay.strategy)
        except ValueError:
            strategy = config.strategy
    if strategy not in STRATEGIES:
        strategy = DELAY_BY_TIME
    interval_second = delay.intervalSecond if delay is not None and delay.intervalSecond > 0 else 0
    try:
        health_check_second = int(delay.healthCheckIntervalSecond) if delay is not None else 0
    except (TypeError, ValueError):
        health_check_second = 0
    return LosslessOptions(
        delay_register_enable=getattr(delay, "enable", True) if delay is not None else True,
        delay_register_interval_ms=interval_second * 1000 if interval_second > 0 else config.delay_register_interval,
        health_check_interval_ms=(
            health_check_second * 1000 if health_check_second > 0 else config.health_check_interval
        ),
        strategy=strategy,
        health_check_path=delay.healthCheckPath if delay is not None and delay.healthCheckPath else config.health_check_path,
        warmup_enable=bool(getattr(warmup, "enable", False)) if warmup is not None else False,
        warmup_interval_second=int(getattr(warmup, "intervalSecond", 0) or 0) if warmup is not None else 0,
        warmup_curvature=float(warmup.curvature) if warmup is not None else 1.0,
        warmup_overload_protection=(
            bool(getattr(warmup, "enableOverloadProtection", False)) if warmup is not None else False
        ),
        warmup_overload_threshold=int(getattr(warmup, "overloadProtectionThreshold", 0) or 0) if warmup else 0,
        offline_enable=getattr(offline, "enable", True) if offline is not None else True,
        readiness_enable=getattr(readiness, "enable", True) if readiness is not None else True,
    )


def _options_from_config(config: LosslessConfig) -> LosslessOptions:
    return LosslessOptions(
        delay_register_enable=True,
        delay_register_interval_ms=config.delay_register_interval,
        health_check_interval_ms=config.health_check_interval,
        strategy=config.strategy,
        health_check_path=config.health_check_path,
        warmup_enable=False,
        warmup_interval_second=0,
        warmup_curvature=1.0,
        warmup_overload_protection=False,
        warmup_overload_threshold=0,
        offline_enable=True,
        readiness_enable=True,
    )


def _parse_ctime(instance: Instance) -> Optional[datetime]:
    value = instance.instance.ctime.value if instance.instance.HasField("ctime") else ""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class _WarmupInstance(Instance):
    """Present a warmed-up instance weight without mutating the cached snapshot."""

    def __init__(self, instance: Instance, weight: int):
        super().__init__(instance.instance, instance.service_key, instance.local_value)
        self._warmup_weight = weight

    def get_weight(self):
        return self._warmup_weight


class LosslessManager:
    """Coordinate delayed registration, lossless deregister and warmup weights."""

    def __init__(self, config: Configuration, connector) -> None:
        self._config = config
        self._lossless_config = config.get_provider().get_lossless()
        self._connector = connector
        self.enabled = self._lossless_config.enable
        self._action_providers: Dict[LosslessInstance, LosslessActionProvider] = {}
        self._register_statuses: Dict[LosslessInstance, RegisterStatus] = {}
        self._register_timestamps: Dict[LosslessInstance, float] = {}
        self._register_tasks: Dict[LosslessInstance, asyncio.Task] = {}
        self._rules_cache: Dict[tuple, tuple] = {}
        self._rules_fetching: set = set()
        self._rule_refresh_tasks: Dict[tuple, set] = {}
        self._closed = False

    def set_action_provider(self, instance: LosslessInstance, provider: LosslessActionProvider) -> None:
        self._action_providers[instance] = provider

    def get_action_provider(self, instance: LosslessInstance) -> Optional[LosslessActionProvider]:
        return self._action_providers.get(instance)

    async def fetch_rules(self, namespace: str, service: str) -> List:
        """Fetch lossless rules from the server and refresh the local cache."""
        key = (namespace, service)
        try:
            request = InstanceDiscoverRequest(
                type=DISCOVER_TYPE_LOSSLESS, name=service, namespace=namespace, revision="",
            )
            response = await self._connector.discover(request)
            rules = _extract_rules(response)
        except Exception as error:
            lossless_logger.warning("failed to fetch lossless rules for %s/%s: %s", namespace, service, error)
            cached = self._rules_cache.get(key)
            return list(cached[0]) if cached else []
        revision = response.service.revision.value if response.service.HasField("revision") else ""
        self._rules_cache[key] = (rules, revision, time.monotonic())
        return list(rules)

    def touch_rules(self, namespace: str, service: str) -> None:
        """Refresh stale rules in the background; used by the consumer warmup path."""
        if self._closed:
            return
        key = (namespace, service)
        cached = self._rules_cache.get(key)
        if cached is not None and time.monotonic() - cached[2] < RULE_REFRESH_INTERVAL_SECONDS:
            return
        if key in self._rules_fetching:
            return

        async def refresh() -> None:
            try:
                await self.fetch_rules(namespace, service)
            finally:
                self._rules_fetching.discard(key)

        self._rules_fetching.add(key)
        task = asyncio.create_task(refresh(), name=f"polaris-lossless-rules-{namespace}-{service}")
        self._rule_refresh_tasks.setdefault(key, set()).add(task)
        task.add_done_callback(self._rule_refresh_tasks[key].discard)

    def _cached_rules(self, namespace: str, service: str) -> List:
        cached = self._rules_cache.get((namespace, service))
        return list(cached[0]) if cached else []

    async def effective_options(self, instance: LosslessInstance) -> LosslessOptions:
        """Resolve server rules first, then fall back to local configuration."""
        rules = await self.fetch_rules(instance.namespace, instance.service)
        rule = _match_rule(instance, rules)
        if rule is not None:
            return _options_from_rule(rule, self._lossless_config)
        return _options_from_config(self._lossless_config)

    def cached_options(self, instance: LosslessInstance) -> LosslessOptions:
        rule = _match_rule(instance, self._cached_rules(instance.namespace, instance.service))
        if rule is not None:
            return _options_from_rule(rule, self._lossless_config)
        return _options_from_config(self._lossless_config)

    async def lossless_register(self, instance: LosslessInstance) -> None:
        """Gate the real registration behind delay or health checking."""
        provider = self._action_providers.get(instance)
        if provider is None:
            lossless_logger.warning("no lossless action provider for %s, skip lossless register", instance)
            return
        if not self.enabled:
            lossless_logger.info("lossless disabled, register %s directly", instance)
            await self._do_register(instance)
            return
        options = await self.effective_options(instance)
        if not options.delay_register_enable:
            lossless_logger.info("delay register disabled for %s, register now", instance)
            await self._do_register(instance)
            return
        previous = self._register_tasks.pop(instance, None)
        if previous is not None and not previous.done():
            previous.cancel()
        if options.strategy == DELAY_BY_HEALTH_CHECK and provider.is_enable_health_check():
            self._register_tasks[instance] = asyncio.create_task(
                self._run_health_check_register(instance, options),
                name=f"polaris-lossless-register-{instance.namespace}-{instance.service}",
            )
        else:
            self._register_tasks[instance] = asyncio.create_task(
                self._run_delayed_register(instance, options),
                name=f"polaris-lossless-register-{instance.namespace}-{instance.service}",
            )

    async def _run_delayed_register(self, instance: LosslessInstance, options: LosslessOptions) -> None:
        await asyncio.sleep(options.delay_register_interval_ms / 1000)
        if self._closed:
            return
        lossless_logger.info("lossless delay finished for %s, start register", instance)
        await self._do_register(instance)

    async def _run_health_check_register(self, instance: LosslessInstance, options: LosslessOptions) -> None:
        provider = self._action_providers.get(instance)
        if provider is None:
            return
        while not self._closed:
            await asyncio.sleep(options.health_check_interval_ms / 1000)
            if self._closed:
                return
            try:
                ready = await provider.do_health_check()
            except Exception as error:
                lossless_logger.warning("lossless health check failed for %s: %s", instance, error)
                ready = False
            if ready:
                lossless_logger.info("lossless health check passed for %s, start register", instance)
                await self._do_register(instance)
                return

    async def _do_register(self, instance: LosslessInstance) -> None:
        provider = self._action_providers.get(instance)
        if provider is None:
            return
        properties = InstanceProperties()
        await provider.do_register(properties)
        self._register_statuses[instance] = RegisterStatus.REGISTERED
        self._register_timestamps[instance] = time.time()

    async def lossless_deregister(self, instance: LosslessInstance) -> None:
        """Deregister immediately so consumers can remove the instance."""
        provider = self._action_providers.get(instance)
        if provider is None:
            lossless_logger.warning("no lossless action provider for %s, skip lossless deregister", instance)
            return
        task = self._register_tasks.pop(instance, None)
        if task is not None and not task.done():
            task.cancel()
        await provider.do_deregister()
        self._register_statuses[instance] = RegisterStatus.UNREGISTERED

    def check_register_status(self) -> RegisterStatus:
        """Return REGISTERED only when every tracked instance is registered."""
        if not self._action_providers:
            return RegisterStatus.UNREGISTERED
        for instance, provider in self._action_providers.items():
            if not self._readiness_enabled(instance):
                continue
            if self._register_statuses.get(instance) != RegisterStatus.REGISTERED:
                return RegisterStatus.UNREGISTERED
        return RegisterStatus.REGISTERED

    def _readiness_enabled(self, instance: LosslessInstance) -> bool:
        return self.cached_options(instance).readiness_enable

    def _offline_instances(self) -> List[LosslessInstance]:
        return [
            instance for instance in self._action_providers
            if self.cached_options(instance).offline_enable
        ]

    async def offline_all(self):
        """Deregister every instance that has lossless offline enabled."""
        instances = self._offline_instances()
        if not instances:
            return None
        for instance in instances:
            await self.lossless_deregister(instance)
        return instances

    def apply_warmup_weights(self, instances: ServiceInstances) -> ServiceInstances:
        """Return a snapshot with warmup-adjusted weights, matching Java overload protection."""
        namespace = instances.get_namespace()
        service = instances.get_service()
        rules = self._cached_rules(namespace, service)
        if not rules or not instances.instances:
            return instances
        now = time.time()
        warming = []
        for node in instances.instances:
            rule = _match_rule(LosslessInstance(
                namespace=node.get_namespace(), service=node.get_service(),
                host=node.get_host(), port=node.get_port(), metadata=dict(node.get_metadata() or {}),
            ), rules)
            if rule is None:
                continue
            options = _options_from_rule(rule, self._lossless_config)
            if not options.warmup_enable or options.warmup_interval_second <= 0:
                continue
            ctime = _parse_ctime(node)
            if ctime is None:
                continue
            uptime = max(0.0, now - ctime.timestamp())
            if uptime >= options.warmup_interval_second:
                continue
            warming.append((node, options, uptime))
        if not warming:
            return instances
        total = len(instances.instances)
        warming_percent = len(warming) * 100 // total
        for _, options, _ in warming:
            if options.warmup_overload_protection and warming_percent >= options.warmup_overload_threshold:
                return instances
        result = _copy_instances(instances)
        for node, options, uptime in warming:
            base_weight = node.get_weight()
            ratio = uptime / options.warmup_interval_second
            weight = min(base_weight, math.ceil(math.pow(ratio, options.warmup_curvature) * base_weight))
            if weight < base_weight:
                index = result.instances.index(node)
                result.instances[index] = _WarmupInstance(node, weight)
        return result

    def warmup_start_timestamp(self, instance: LosslessInstance) -> Optional[float]:
        return self._register_timestamps.get(instance)

    async def close(self) -> None:
        self._closed = True
        tasks = [task for task in self._register_tasks.values() if not task.done()]
        for task_set in self._rule_refresh_tasks.values():
            tasks.extend(task for task in task_set if not task.done())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._register_tasks.clear()
        self._rule_refresh_tasks.clear()


def _copy_instances(instances: ServiceInstances) -> ServiceInstances:
    import copy

    result = copy.copy(instances)
    result.instances = list(instances.instances)
    return result


class HttpLosslessActionProvider(LosslessActionProvider):
    """Action provider that wraps real register/deregister and HTTP health checks."""

    def __init__(self, instance: LosslessInstance, register_action, deregister_action,
                 strategy_resolver, health_check_path_resolver) -> None:
        self._instance = instance
        self._register_action = register_action
        self._deregister_action = deregister_action
        self._strategy_resolver = strategy_resolver
        self._health_check_path_resolver = health_check_path_resolver

    def get_name(self) -> str:
        return "http"

    async def do_health_check(self) -> bool:
        path = self._health_check_path_resolver()
        url = f"http://127.0.0.1:{self._instance.port}{path}"
        timeout = ClientTimeout(total=2)
        try:
            async with ClientSession(timeout=timeout) as session:
                async with session.get(url, headers={"User-Agent": "polaris"}) as response:
                    return response.status < 400
        except Exception:
            return False

    def is_enable_health_check(self) -> bool:
        return self._strategy_resolver() == DELAY_BY_HEALTH_CHECK

    async def do_register(self, instance_properties: InstanceProperties):
        await self._register_action(instance_properties)

    async def do_deregister(self):
        await self._deregister_action()


def lossless_http_handlers(manager: LosslessManager):
    """Build the Java-compatible /offline and /readiness endpoints."""

    async def offline(request: web.Request) -> web.Response:
        remote = request.remote or ""
        try:
            loopback = ipaddress.ip_address(remote).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            return web.Response(text="only localhost can call this path", status=403)
        if not manager.enabled:
            return web.Response(text="no policy", status=500)
        if not manager._action_providers:
            return web.Response(text="no action", status=200)
        instances = manager._offline_instances()
        if not instances:
            return web.Response(status=404)
        try:
            await manager.offline_all()
        except Exception as error:
            lossless_logger.error("failed to execute lossless offline: %s", error)
            return web.Response(text=f"failed: {error}", status=500)
        return web.Response(text="ok", status=200)

    async def readiness(request: web.Request) -> web.Response:
        del request
        instances = [
            instance for instance in manager._action_providers
            if manager._readiness_enabled(instance)
        ]
        if not instances:
            return web.Response(status=404)
        status = manager.check_register_status()
        return web.Response(text=status.value, status=200 if status == RegisterStatus.REGISTERED else 503)

    return (
        ("*", "/offline", offline),
        ("GET", "/readiness", readiness),
        ("GET", "/online", readiness),
    )
