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
from polaris.plugin.service_router.base import BaseServiceRouter, RouteInfo, RouteResult
from polaris.plugin_manager import InitContext, PluginType, register_plugin


@register_plugin(PluginType.SERVICE_ROUTER, DefaultConf.DefaultServiceRouterIsolated)
class IsolatedRouter(BaseServiceRouter):
    """Drop isolated instances and instances whose weight is zero."""

    def __init__(self, init_ctx: InitContext = None):
        self.init_ctx = init_ctx

    def enable(self, route_info: RouteInfo, instances: service.ServiceInstances) -> bool:
        return route_info.chain_enables.get(DefaultConf.DefaultServiceRouterIsolated, True)

    def get_filtered_instances(self, route_info: RouteInfo, instances: service.ServiceInstances) -> RouteResult:
        selected = [instance for instance in instances.get_instances()
                    if instance.get_weight() != 0 and not instance.is_isolated()]
        return RouteResult(selected)
