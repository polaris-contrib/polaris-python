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

from .base import BaseLoadBalancer
from ...pkg.model.service import ServiceInstances, Instance
import random
from ...pkg.model.error import SDKError, ErrorCode
from polaris.plugin_manager import PluginType, register_plugin, InitContext


@register_plugin(PluginType.LOAD_BALANCE, 'weightedRandom')
class WeightedRandomLoadBalancer(BaseLoadBalancer):
    def __init__(self, init_ctx: InitContext = None):
        self.config = init_ctx.config if init_ctx is not None else None
        self.init_ctx = init_ctx

    def choose_instance(self, instances: ServiceInstances) -> Instance:
        svc_instances = instances.get_instances()
        if len(svc_instances) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInstanceNotFound, "instances of %s:%s not found for load balance"
                           % (instances.get_namespace(), instances.get_service()))
        total_weight = 0
        curr_sum = 0
        ret_instance = None
        for i in range(len(svc_instances)):
            total_weight += svc_instances[i].get_weight()
        if total_weight == 0:
            return None
        ra = random.randint(1, total_weight)
        for i in range(len(svc_instances)):
            curr_sum += svc_instances[i].get_weight()
            if ra <= curr_sum:
                ret_instance = svc_instances[i]
                break
        return ret_instance


__all__ = ["WeightedRandomLoadBalancer"]
