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
from typing import Dict

from polaris.pkg.model.core import ServiceEventKey
from polaris.pkg.model.service import ServiceInstances

__all__ = ["BaseLocalRegistry", "InstanceFilter"]


class InstanceFilter:
    def __init__(self, namespace: str, service: str, is_internal_request: bool, include_cache=False):
        self.namespace = namespace
        self.service = service
        self.is_internal_request = is_internal_request
        self.include_cache = include_cache


class BaseLocalRegistry(ABC):
    """
    获取服务实例列表
    """

    @abstractmethod
    def get_instances(self, instance_filter: InstanceFilter) -> ServiceInstances:
        pass

    def get_services(self) -> Dict[ServiceEventKey, bool]:
        pass

    async def expire_services(self):
        """Release idle resources owned by this registry."""
        return []
