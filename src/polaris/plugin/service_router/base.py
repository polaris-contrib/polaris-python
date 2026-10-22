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

from abc import ABC, abstractmethod
from typing import Dict, List

from polaris.pkg.model import service
from polaris.pkg.model.rule import ServiceRule
from polaris.pkg.model.service import ServiceInfo

__all__ = [
    "BaseServiceRouter",
    "CanaryMetaKey",
    "CanaryMetadataEnable",
    "MetadataFailoverKey",
    "NearbyKeyAreaWithCampus",
    "NearbyKeyAreaWithRegion",
    "NearbyKeyAreaWithZone",
    "NearbyMetadataEnable",
    "RouteInfo",
    "RouteResult",
    "SetEnableKey",
    "SetEnableValue",
    "SetNameKey",
]

# 保存客户端地域信息 idc key
NearbyKeyAreaWithCampus = "client_area_campus"
# 保存客户端地域信息 zone key
NearbyKeyAreaWithZone = "client_area_zone"
# 保存客户端地域信息 region key
NearbyKeyAreaWithRegion = "client_area_region"

NearbyMetadataEnable = "internal-enable-nearby"
CanaryMetadataEnable = "internal-canary"
CanaryMetaKey = "canary"

SetEnableKey = "internal-enable-set"
SetEnableValue = "Y"
SetNameKey = "internal-set-name"
MetadataFailoverKey = "internal-metadata-failover-type"


class RouteInfo:
    def __init__(self, source_service: ServiceInfo = None, source_routerule: ServiceRule = None,
                 dest_service: ServiceInfo = None, dest_routerule: ServiceRule = None,
                 include_unhealthy_instances: bool = False, include_circuitbreak_instances: bool = False,
                 canary: str = "", metadata: Dict[str, str] = None,
                 metadata_failover_type: str = None):
        # 源服务信息
        self.source_service = source_service
        # 源路由规则
        self.source_routerule = source_routerule
        # 目标服务信息
        self.dest_service = dest_service
        # 目标路由规则
        self.dest_routerule = dest_routerule
        # 是否包含不健康的服务实例，默认false
        self.include_unhealthy_instances = include_unhealthy_instances
        # 是否包含被熔断的服务实例，默认false
        self.include_circuitbreak_instances = include_circuitbreak_instances
        # 标识是否不需要执行全死全活兜底
        # 对于全死全活插件，以及就近路由插件等，已经做了最小实例数检查，则可以设置该属性为true
        # 需要插件内部进行设置
        self.ignore_filter_only_on_end_chain = False
        # 可动态调整路由插件是否启用，不存在或者为true代表启用
        # key为路由插件的id
        self.chain_enables = {}
        # 金丝雀
        self.canary = canary
        # 请求 metadata，用于 metadataRouter
        self.metadata = {} if metadata is None else metadata
        # none / all / others；None 表示使用服务或插件配置
        self.metadata_failover_type = metadata_failover_type


class RouteResult:
    def __init__(self, instances: List[service.Instance]):
        # 根据路由规则过滤后的目标服务实例列表，假如重定向则列表为空
        self.instances = instances


class BaseServiceRouter(ABC):
    """
    获取规则过滤后的服务实例列表
    """

    @abstractmethod
    def get_filtered_instances(self, route_info: RouteInfo, instances: service.ServiceInstances) -> RouteResult:
        pass

    def enable(self, route_info: RouteInfo, instances: service.ServiceInstances) -> bool:
        return True
