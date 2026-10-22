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

from polaris.plugin.local_registry.local_cache import InstanceFilter
from polaris.pkg.model.rule import ServiceRule
from polaris.pkg.model.service import ServiceInstances
from polaris.plugin.local_registry.local_cache import LocalCache
from polaris.pkg.model.core import ServiceKey
from polaris.plugin.local_registry.local_cache import ServiceUpdateRequest
from typing import Dict
from polaris.api.log import get_logger
import copy
from polaris.plugin.circuit_breaker.composite import CircuitBreakResult
from polaris.pkg.model.error import ErrorCode, SDKError

logger = get_logger("cache")


class RealTimeLimitTask:
    def __init__(self, svc: ServiceKey = None, ins_id: str = None, host: str = None, port: int = None,
                 cb_name: str = None):
        self.service_key = svc
        self.instance_id = ins_id
        self.host = host
        self.port = port
        self.cb_name = cb_name

    def get_host(self):
        return self.host

    def get_port(self):
        return self.port

    def get_instance_id(self):
        return self.instance_id

    def get_service_key(self):
        return self.service_key

    def get_cb_name(self):
        return self.cb_name


class CacheFilter:
    def __init__(self, namespace: str, service: str, dest_instance_fileter: InstanceFilter):
        self.namespace = namespace
        self.service = service
        self.desc_instances_filter = dest_instance_fileter

    def to_context_key(self):
        pass


class CacheResult:
    def __init__(self, source_route_rule: ServiceRule = None, dest_route_rule: ServiceRule = None,
                 dest_instances: ServiceInstances = None):
        self.source_route_rule = source_route_rule
        self.dest_route_rule = dest_route_rule
        self.dest_instances = dest_instances
        self.combineContext = ""


async def get_load_cache_values(registry: LocalCache, filters: CacheFilter, load: bool,
                                use_discover_cache=True, timeout=None) -> CacheResult:
    result = CacheResult()
    instances = registry.get_instances(instance_filter=filters.desc_instances_filter)
    if instances and instances.is_initialized():
        result.dest_instances = copy.copy(instances)
    elif load:
        logger.info("miss local cache and begin to load remote value for %s", filters.desc_instances_filter.__dict__)
        try:
            await registry.load_instances(filters.service, filters.namespace, use_discover_cache, timeout=timeout)
        except SDKError as error:
            if error.err_code not in (ErrorCode.ErrCodeNetworkError, ErrorCode.ErrCodeAPITimeoutError):
                raise
            fallback_filter = copy.copy(filters.desc_instances_filter)
            fallback_filter.include_cache = True
            instances = registry.get_instances(fallback_filter)
            if instances is None:
                raise
            logger.warning("remote discovery unavailable; using local snapshot for %s/%s",
                           filters.namespace, filters.service)
        else:
            instances = registry.get_instances(instance_filter=filters.desc_instances_filter)
        result.dest_instances = copy.copy(instances) if instances is not None else None
    else:
        return None
    return result


def build_instance_property(now, allowed_request: int, instances):
    pass


def build_service_update_request(svc: ServiceKey, results: Dict[str, CircuitBreakResult]) -> ServiceUpdateRequest:
    request = ServiceUpdateRequest(service=svc.get_service(), namespace=svc.get_namespace())
    for cb_name, result in results.items():
        pass
