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

import asyncio
import threading

from ...pkg.model.service import ServiceInstances, Instance, new_service_instances, DefaultInstanceLocalValue
from ...pkg.model.server import InstanceDiscoverRequest
from ...pkg.model.rule import ServiceRule, new_simple_service_rule
from ...pkg.model.core import ServiceKey, ServiceEventKey, EventType
from ...pkg.config.api import get_server_services
from polaris.plugin_manager import PluginType, register_plugin, InitContext, \
    EventType as PluginEventType
from .base import BaseLocalRegistry, InstanceFilter
from ...pkg.flow import impl
from polaris.pkg.model.error import ErrorCode, SDKError, ServerCode
import polaris.pkg.model.context as context
from polaris.api.log import get_logger
from typing import Dict, Any, List
import time

logger = get_logger("cache")

PropertyCircuitBreakerStatus = "CircuitBreakerStatus"
EmptyRule = new_simple_service_rule(EventType.Unknown, None, "")


class CacheObject:
    def __init__(self, invalid: bool = False):
        self.invalid: bool = invalid
        self.last_visit_time: float = time.monotonic()
        self.value = None
        self.remote_updated = False
        self.lock = threading.RLock()
        self.load_lock = asyncio.Lock()
        self.loading = False

    def is_remote_updated(self) -> bool:
        """Report whether a remote discover response has replaced this snapshot."""
        return self.remote_updated

    def get_value(self, update_ts: bool):
        if update_ts:
            self.last_visit_time = time.monotonic()

        return self.value

    def set_value(self, value):
        self.value = value


class InstanceProperties:
    def __init__(self, service: ServiceKey = None, ID: str = "", properties: Dict[str, Any] = None):
        self.service = service
        self.ID = ID
        if properties is None:
            self.properties = {}
        else:
            self.properties = properties

    def set_id(self, ID):
        self.ID = ID

    def set_property(self, property, value):
        self.properties[property] = value


class ServiceUpdateRequest(ServiceKey):
    def __init__(self, namespace: str = "", service: str = ""):
        super(ServiceUpdateRequest, self).__init__(namespace=namespace, service=service)
        self.properties: List[InstanceProperties] = []


class InstanceRegistry:
    def get_instances(self, instance_filter: InstanceFilter):
        pass

    def load_instances(self, service: str, namespace: str):
        pass

    def update_instances(self, update_request: ServiceUpdateRequest):
        pass

    def get_services(self):
        pass

# 配置获取的过滤器
class RuleFilter:
    def __init__(self, service_event_key: ServiceEventKey):
        self.service_event_key = service_event_key


async def load_file_cache(engine, request):
    """Read one instance backup without using its modification time as a freshness gate."""
    response = await engine.file_cache.async_get(request, expire=None)
    if response is None:
        return None
    # Legacy snapshots did not always carry the response type, but must identify the service.
    if (response.code.value != ServerCode.ExecuteSuccess
            or response.type not in (0, request.type)
            or response.service.name.value != request.name
            or response.service.namespace.value != request.namespace):
        logger.warning("ignore invalid file cache for %s/%s type %s", request.namespace, request.name, request.type)
        return None
    logger.warning("use file cache %s", request.name)
    return response


@register_plugin(PluginType.LOCAL_CACHE, 'inmemory')
class LocalCache(BaseLocalRegistry):
    def __init__(self, init_ctx: InitContext = None):
        self.init_ctx = init_ctx
        self.config = self.init_ctx.config
        self._cache_lock = threading.RLock()
        self.service_map: Dict[ServiceEventKey, CacheObject] = {}
        self.services: Dict[ServiceEventKey, bool] = {}
        self._system_services = {
            (cluster.service_key.namespace, cluster.service_key.service)
            for cluster in get_server_services(self.config).values()
        }

    def get_instances(self, instance_filter: InstanceFilter) -> ServiceInstances:
        """
        从缓存中获取实例
        :param instance_filter: 过滤器
        :return: ServiceInstances
        """
        service_key = ServiceEventKey(instance_filter.namespace, instance_filter.service, EventType.Instance)
        with self._cache_lock:
            cache_obj = self.service_map.get(service_key)
            if cache_obj is None or cache_obj.invalid:
                return None
            value = cache_obj.get_value(not instance_filter.is_internal_request)
            if value is None or (not cache_obj.remote_updated and not instance_filter.include_cache):
                return None
            return value

    async def load_instances(self, service: str, namespace: str, use_discover_cache=True, timeout=None):
        """
        通过service和namespace加载instance到缓存中
        :param use_discover_cache:
        :param service: 服务名
        :param namespace: 命名空间
        :return: None
        """
        service_key = ServiceEventKey(namespace, service, EventType.Instance)
        await self._load_instances(service_key, use_discover_cache, timeout)

    async def _discover(self):
        pass

    async def _load_instances(self, service_key: ServiceEventKey, use_discover_cache: bool = True, timeout=None):
        while True:
            with self._cache_lock:
                cache_obj = self.service_map.get(service_key)
                if cache_obj is None:
                    cache_obj = CacheObject()
                    self.service_map[service_key] = cache_obj
            # Keep loads behind eviction cleanup before creating a new generation.
            async with cache_obj.load_lock:
                if self.service_map.get(service_key) is not cache_obj:
                    continue
                if cache_obj.remote_updated and cache_obj.value is not None:
                    cache_obj.get_value(True)
                    return
                cache_obj.loading = True
                try:
                    await self._load_value(service_key, cache_obj, use_discover_cache, timeout)
                    cache_obj.get_value(True)
                finally:
                    cache_obj.loading = False
                return

    def _service_instances(self, response, old_instances=None, loaded_from_file=False):
        def create_local_value(instance):
            event_handle_list = self.init_ctx.plugins.get_event_subscriber(PluginEventType.ON_LOCALVALUE_CREATED)
            local_value = DefaultInstanceLocalValue()
            for handle in event_handle_list:
                handle.on_plugin_event(PluginEventType.ON_LOCALVALUE_CREATED, local_value)
            return local_value

        return ServiceInstances.new_from_discover_rsp(
            response, create_local_value, old_instances=old_instances, loaded_from_file=loaded_from_file,
        )

    async def _load_value(self, service_key, cache_obj, use_discover_cache, timeout=None):
        if service_key.event_type != EventType.Instance:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "only instance resources are cached")
        engine = self.init_ctx.value_ctx.get_value(context.ContextKeyEngine)
        update_task = engine.update_task_set.get(service_key)
        if update_task is None or update_task.cache_obj is not cache_obj:
            interval = self.config.get_consumer().get_local_cache().service_refresh_interval
            system = self.config.get_global().get_system()
            for cluster in (system.get_discover_cluster(), system.get_health_check_cluster(),
                            system.get_monitor_cluster()):
                if (service_key.namespace, service_key.service) == (cluster.namespace, cluster.service):
                    interval = cluster.refresh_interval
            update_task = impl.ServiceUpdateTask(
                service_key, cache_obj, interval,
                int(time.time() * 1000),
            )
            engine.update_task_set[service_key] = update_task

        req = InstanceDiscoverRequest(1, service_key.service, service_key.namespace)
        if cache_obj.value is None:
            disk = await load_file_cache(engine, req)
            if disk is not None:
                cache_obj.set_value(self._service_instances(disk, loaded_from_file=True))
        if cache_obj.value is not None:
            req.revision = cache_obj.value.revision

        client = engine.svc_connector
        success_loaded = False
        err = None
        ret = None
        api_config = self.config.get_global().get_api()
        try:
            # Reconnecting streams may never raise, so bound the entire initial remote wait.
            async with asyncio.timeout((timeout or api_config.get_timeout()) / 1000):
                for attempt in range(api_config.get_max_retry_times() + 1):
                    try:
                        ret = await client.discover(req, use_discover_cache)
                    except SDKError as e:
                        err = e
                        if e.server_code == ServerCode.NotFoundService:
                            raise
                        if e.err_code == ErrorCode.ErrCodeDataNotChange and cache_obj.value is not None:
                            cache_obj.remote_updated = True
                            self.services[service_key] = True
                            return
                        if e.err_code not in (ErrorCode.ErrCodeNetworkError, ErrorCode.ErrCodeAPITimeoutError):
                            raise
                        logger.error("Failed to do discover %s and retry: %s", service_key.__dict__, repr(e))
                        if attempt < api_config.get_max_retry_times():
                            await asyncio.sleep(api_config.get_retry_interval() / 1000)
                        continue
                    else:
                        success_loaded = True
                        engine.file_cache.save(req, ret)
                        break
        except SDKError as error:
            if error.server_code == ServerCode.NotFoundService:
                await self.remove_service(service_key, cache_obj)
            raise
        except TimeoutError:
            if err is None:
                err = SDKError(ErrorCode.ErrCodeAPITimeoutError,
                               "Timed out loading %s/%s type %s" % (req.namespace, req.name, req.type))
                logger.warning("%s", err)
        if not success_loaded:
            if err is None:
                err = SDKError(ErrorCode.ErrCodeAPITimeoutError,
                               "Timed out loading %s/%s type %s" % (req.namespace, req.name, req.type))
            raise err

        cache_obj.set_value(self._service_instances(ret, old_instances=cache_obj.value))
        cache_obj.remote_updated = True
        self.services[service_key] = True

    async def remove_service(self, service_key, cache_obj):
        """Delete one generation and its backup before allowing a replacement load."""
        if self.service_map.get(service_key) is not cache_obj or cache_obj.invalid:
            return
        cache_obj.invalid = True
        self.services.pop(service_key, None)
        engine = self.init_ctx.value_ctx.get_value(context.ContextKeyEngine)
        try:
            await engine.stop_service_update(service_key, cache_obj)
        finally:
            if self.service_map.get(service_key) is cache_obj:
                self.service_map.pop(service_key)

    def get_service_revision(self, service, namespace, type):
        service_key = ServiceEventKey(namespace, service, type)
        cached_object = self.service_map.get(service_key, None)
        if cached_object is None or cached_object.invalid or cached_object.value is None:
            return None

        return cached_object.value.revision

    def update_instances(self, update_request: ServiceUpdateRequest):
        """
        更新实例的本地信息
        :param update_request:
        :return:
        """

        service_key = ServiceEventKey(update_request.namespace, update_request.service, EventType.Instance)
        cache_obj = self.service_map.get(service_key, None)
        if cache_obj is None:
            raise Exception("cache not exists in update_instances %s" % service_key.__dict__)

        for p in update_request.properties:
            service_instances = self.get_instances(InstanceFilter(p.service.namespace, p.service.service, True))
            local_value = service_instances.get_instance_local_value(p.ID)
            if local_value is None:
                continue

            for k, v in p.properties.items():
                if k == PropertyCircuitBreakerStatus:
                    local_value.set_circuit_breaker_status(v)

    def update_service(self, service_key: ServiceEventKey, service_instance: ServiceInstances):
        cache_object = self.service_map.get(service_key, None)
        if cache_object is None or cache_object.invalid:
            logger.error("updating object that is not exist in cache %s", service_key.__dict__)
            return False

        with cache_object.lock:
            cache_object.set_value(service_instance)
            cache_object.remote_updated = True
        self.services[service_key] = True

        return True

    # 非阻塞获取配置信息
    def get_service_rule(self, rule_filter: RuleFilter) -> ServiceRule:
        with self._cache_lock:
            cache_obj = self.service_map.get(rule_filter.service_event_key)
            if cache_obj is None or cache_obj.invalid:
                return EmptyRule
            return cache_obj.get_value(True) or EmptyRule

    def get_services(self):
        return self.services.copy()

    def _is_expired(self, service_key, cache_obj, now):
        if cache_obj.invalid or cache_obj.loading:
            return False
        if (service_key.namespace, service_key.service) in self._system_services:
            return False
        expire_time = self.config.get_consumer().get_local_cache().service_expire_time
        return (now - cache_obj.last_visit_time) * 1000 >= expire_time

    async def expire_services(self):
        """Release idle resources and their discovery streams on the context owner loop."""
        engine = self.init_ctx.value_ctx.get_value(context.ContextKeyEngine)
        expired = []
        for service_key, cache_obj in list(self.service_map.items()):
            if not self._is_expired(service_key, cache_obj, time.monotonic()):
                continue
            async with cache_obj.load_lock:
                with self._cache_lock:
                    if self.service_map.get(service_key) is not cache_obj:
                        continue
                    if not self._is_expired(service_key, cache_obj, time.monotonic()):
                        continue
                    cache_obj.invalid = True
                    self.services.pop(service_key, None)
                try:
                    await engine.stop_service_update(service_key, cache_obj)
                except Exception as error:
                    logger.error("failed to clean idle resource %s: %s", service_key.__dict__, error)
                finally:
                    with self._cache_lock:
                        if self.service_map.get(service_key) is cache_obj:
                            self.service_map.pop(service_key)
                expired.append(service_key)
                logger.info("evicted idle cache resource %s", service_key.__dict__)
        return expired

    def destroy(self):
        """Release this context's memory snapshots after its owner loop has stopped."""
        self.service_map.clear()
        self.services.clear()
