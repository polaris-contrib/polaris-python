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

from random import randint
from polaris.plugin_manager import PluginType, register_plugin
from polaris.pkg.model.service import ServiceInstances, Instance
from ...pkg.model.error import ErrorCode, SDKError
from polaris.plugin_manager import InitContext

from .base import BaseLoadBalancer


@register_plugin(PluginType.LOAD_BALANCE, 'random')
class RandomLoadBalancer(BaseLoadBalancer):
    def __init__(self, init_ctx: InitContext = None):
        self.init_ctx = init_ctx

    def choose_instance(self, instances: ServiceInstances) -> Instance:
        svc_instances = instances.get_instances()
        if len(svc_instances) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInstanceNotFound, "instances of %s:%s not found for load balance"
                           % (instances.get_namespace(), instances.get_service()))
        n = randint(0, len(svc_instances) - 1)
        return svc_instances[n]


__all__ = ["RandomLoadBalancer"]
