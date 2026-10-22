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

from polaris.pkg.model.service import Instance
from typing import List
from polaris.api.log import get_logger

from .base import RouteInfo

logger = get_logger("route")


# 从subset中选取可用的实例
def get_available_instances(
        instances: List[Instance], route_info: RouteInfo, percent_of_min_instances: float) -> List[Instance]:
    available_instances = calc_available_instances(
        route_info.include_unhealthy_instances, route_info.include_circuitbreak_instances, instances)

    min_instances = int(percent_of_min_instances * len(instances))
    if len(instances) > 0 and len(available_instances) <= min_instances:
        logger.warning("all instance is down and return all for %s", route_info.dest_service.get_service())
        available_instances = instances
    return available_instances


# 计算subset中的可用实例
def calc_available_instances(
        include_unhealthy_instances: bool, include_circuitbreak_instances: bool, instances: List[Instance]) -> List[
    Instance]:
    available_instances = []
    if len(instances) == 0:
        return available_instances
    for i in range(len(instances)):
        instance = instances[i]
        if not include_unhealthy_instances and not instance.is_healthy():
            continue
        if not include_circuitbreak_instances:
            cb_status = instance.get_circuit_breaker_status()
            if cb_status is not None and not cb_status.is_available():
                continue
        available_instances.append(instance)
    return available_instances
