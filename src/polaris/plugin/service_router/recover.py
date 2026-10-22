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

from polaris.pkg.config.default import DefaultConf
from polaris.pkg.model import service
from polaris.pkg.model.service import CBStatusEnum
from polaris.plugin.service_router.base import BaseServiceRouter, RouteInfo, RouteResult
from polaris.plugin_manager import InitContext, PluginType, register_plugin


def _config_bool(plugin: dict, *keys, default: bool) -> bool:
    for key in keys:
        if key in plugin:
            value = plugin[key]
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)
    return default


@register_plugin(PluginType.SERVICE_ROUTER, DefaultConf.DefaultServiceRouterRecover)
class RecoverRouter(BaseServiceRouter):
    """Keep healthy instances and restore the input list when every instance is unavailable."""

    def __init__(self, init_ctx: InitContext = None):
        plugin = {}
        if init_ctx is not None and init_ctx.config is not None:
            plugin = init_ctx.config.get_consumer().get_service_router().plugin.get(
                DefaultConf.DefaultServiceRouterRecover, {}) or {}
        self.exclude_circuit_break = _config_bool(
            plugin, "excludeCircuitBreakInstances", "exclude_circuit_break_instances", default=True)
        self.all_recover = _config_bool(plugin, "allRecoverEnable", "all_recover_enable", default=True)

    def enable(self, route_info: RouteInfo, instances: service.ServiceInstances) -> bool:
        return route_info.chain_enables.get(DefaultConf.DefaultServiceRouterRecover, True)

    def get_filtered_instances(self, route_info: RouteInfo, instances: service.ServiceInstances) -> RouteResult:
        exclude_circuit_break = self.exclude_circuit_break and not route_info.include_circuitbreak_instances
        healthy = []
        for instance in instances.get_instances():
            if not route_info.include_unhealthy_instances and not instance.is_healthy():
                continue
            if exclude_circuit_break:
                status = instance.get_circuit_breaker_status()
                if status is not None and status.get_status() == CBStatusEnum.Open:
                    continue
            healthy.append(instance)
        if self.all_recover and not healthy:
            return RouteResult(list(instances.get_instances()))
        return RouteResult(healthy)
