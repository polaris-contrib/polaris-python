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
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.plugin.service_router.base import BaseServiceRouter, RouteInfo, RouteResult
from polaris.plugin_manager import InitContext, PluginType, register_plugin

_FAILOVER_KEY = "internal-metadata-failover-type"
_FAILOVERS = {"none", "all", "others"}


def _as_dict(metadata) -> dict:
    if not metadata:
        return {}
    return {key: metadata[key] for key in metadata}


def _matches(instance: service.Instance, required: dict) -> bool:
    metadata = _as_dict(instance.get_metadata())
    return all(metadata.get(key) == value for key, value in required.items())


def _missing_any_key(instance: service.Instance, required: dict) -> bool:
    metadata = _as_dict(instance.get_metadata())
    return any(key not in metadata for key in required)


@register_plugin(PluginType.SERVICE_ROUTER, DefaultConf.DefaultServiceRouterMetadata)
class MetadataRouter(BaseServiceRouter):
    """Keep instances whose metadata contains every requested key and value."""

    def __init__(self, init_ctx: InitContext = None):
        plugin = {}
        if init_ctx is not None and init_ctx.config is not None:
            plugin = init_ctx.config.get_consumer().get_service_router().plugin.get(
                DefaultConf.DefaultServiceRouterMetadata, {}) or {}
        failover = plugin.get("metadataFailOverType", plugin.get("metadata_fail_over_type", "all"))
        if failover not in _FAILOVERS:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "metadataRouter.metadataFailOverType must be one of none, all, others")
        self.failover = failover if failover in _FAILOVERS else "all"

    def enable(self, route_info: RouteInfo, instances: service.ServiceInstances) -> bool:
        if not route_info.chain_enables.get(DefaultConf.DefaultServiceRouterMetadata, True):
            return False
        return bool(_as_dict(route_info.metadata))

    def get_filtered_instances(self, route_info: RouteInfo, instances: service.ServiceInstances) -> RouteResult:
        required = _as_dict(route_info.metadata)
        matched = [instance for instance in instances.get_instances() if _matches(instance, required)]
        if matched:
            return RouteResult(matched)

        failover = self._failover(route_info, instances)
        if failover == "all":
            return RouteResult(list(instances.get_instances()))
        if failover == "others":
            return RouteResult([instance for instance in instances.get_instances()
                                if _missing_any_key(instance, required)])
        service_name = route_info.dest_service.get_service() if route_info.dest_service is not None else ""
        raise SDKError(ErrorCode.ErrCodeRouteRuleNotMatch,
                       f"can not find any instance by metadata for service {service_name}")

    def _failover(self, route_info: RouteInfo, instances: service.ServiceInstances) -> str:
        if route_info.metadata_failover_type in _FAILOVERS:
            return route_info.metadata_failover_type
        service_failover = _as_dict(instances.get_metadata()).get(_FAILOVER_KEY)
        if service_failover in _FAILOVERS:
            return service_failover
        return self.failover
