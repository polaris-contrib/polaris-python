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
import copy
import threading
import time
import traceback
from collections.abc import Coroutine
from typing import Any, TypeVar

from polarismesh_specification.api.v1.service_manage import response_pb2

import polaris.api.log as logger
from polaris.pkg.config.api import ClusterService, get_server_services
from polaris.pkg.flow.base_flow import CacheFilter
from polaris.pkg.flow.base_flow import CacheResult
from polaris.pkg.flow.base_flow import RealTimeLimitTask
from polaris.pkg.flow.base_flow import get_load_cache_values
from polaris.pkg.flow.register import RegisterStateManager
from polaris.pkg.model.context import *
from polaris.pkg.model.core import *
from polaris.pkg.model.engine import BaseEngine
from polaris.pkg.model.rule import *
from polaris.pkg.model.server import *
from polaris.pkg.model.service import *
from polaris.pkg.model import util
from polaris.pkg.version import version
from polaris.plugin.circuit_breaker.composite import CircuitBreakResult
from polaris.plugin.local_registry.file_cache import LocalFileCache
from polaris.plugin.local_registry.local_cache import InstanceFilter
from polaris.plugin.local_registry.local_cache import InstanceProperties
from polaris.plugin.local_registry.local_cache import ServiceUpdateRequest
from polaris.plugin.circuit_breaker.base import BaseCircuitBreaker
from polaris.plugin.load_balancer.base import BaseLoadBalancer
from polaris.plugin.local_registry.base import BaseLocalRegistry
from polaris.plugin.server_connector.base import BaseServerConnector
from polaris.plugin.service_router.base import BaseServiceRouter
from polaris.plugin.service_router.base import NearbyKeyAreaWithCampus
from polaris.plugin.service_router.base import NearbyKeyAreaWithRegion
from polaris.plugin.service_router.base import NearbyKeyAreaWithZone
from polaris.plugin.service_router.base import RouteInfo
from polaris.plugin_manager import Configuration
from polaris.plugin_manager import InitContext
from polaris.plugin_manager import PluginManager
from polaris.plugin_manager import PluginType
from polaris.plugin_manager import setup
from .notify import *
from polaris.pkg.model.error import ErrorCode, SDKError, ServerCode

# 定时任务时间10s
UPDATE_INTERVAL = 10
T = TypeVar("T")
network_logger = logger.get_logger("network")
cache_logger = logger.get_logger("cache")
circuitbreaker_logger = logger.get_logger("circuitbreaker")
route_logger = logger.get_logger("route")
stat_report_logger = logger.get_logger("statReport")


# 保存服务上一次的检测周期的map
keyLastCircuitBreakCheckTimes = "lastCircuitBreakCheckTimes"
# 保存健康探测上一次周期的map
keyLastClientReportTimes = "keyLastClientReportTimes"
# 保存上一次获取discover服务的时间
keyLastDiscoverServiceCheckTimes = "lastDiscoverServiceCheckTimes"


class ServiceUpdateTask:
    def __init__(self, service_key: ServiceEventKey, cache_obj, update_interval: int, last_update_time: int):
        self.service_key = service_key
        self.update_interval = update_interval
        self.last_update_time = last_update_time
        self.cache_obj = cache_obj
        self.runner: asyncio.Task | None = None

    def need_update(self) -> bool:
        cur_time = int(time.time() * 1000)
        return cur_time >= self.last_update_time + self.update_interval


class FutureRequest:
    def __init__(self, request: GetOneInstanceRequest, hash_value: int, do_load_balance: bool):
        self.request = request
        self.hash_value = hash_value
        self.do_load_balance = do_load_balance


class AsyncFlowFuture:
    def __init__(self, request: FutureRequest, filter_request: CacheFilter = None, redirect_times: int = 0,
                 engine: BaseEngine = None):
        self.request = request
        self.filter_request = filter_request
        self.redirect_times = redirect_times
        self.engine = engine


class CheckPeriods:
    def __init__(self, circuit_breaker: int = 0, client_report: int = 0,
                 discover_service: int = 0):
        self.circuit_breaker = circuit_breaker
        self.client_report = client_report
        self.discover_service = discover_service


class Engine(BaseEngine):
    def __init__(self, config: Configuration = None, connector: BaseServerConnector = None,
                 registry: BaseLocalRegistry = None,
                 filter_only_router: BaseServiceRouter = None,
                 circuit_breaker_chain: Dict[str, BaseCircuitBreaker] = None, load_balancer: BaseLoadBalancer = None,
                 max_retry_times: int = 0,
                 router_chain: List[BaseServiceRouter] = None, check_periods: CheckPeriods = None,
                 before_router_chain: List[BaseServiceRouter] = None,
                 after_router_chain: List[BaseServiceRouter] = None,
                 default_api_timeout: int = 0,
                 svc_load_balancer_chain: Dict[str, BaseLoadBalancer] = None,
                 server_service: List[ClusterService] = None,
                 svc_to_router_chain: Dict[str, List[BaseServiceRouter]] = None, global_ctx: ValueContext = None,
                 file_cache: LocalFileCache = None):
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._destroyed = False
        self._destroy_callbacks = []
        self._resources_released = False
        provider_config = config.get_provider() if config is not None else None
        min_register_interval = provider_config.get_min_register_interval() if provider_config else 30000
        self.register_states = RegisterStateManager(
            self._do_register, self._async_heartbeat, min_register_interval,
        )
        # 全局配置
        self.configuration = config
        # 服务端连接器
        self.svc_connector = connector
        # 服务本地缓存
        self.registry = registry
        # 只做过滤的服务器路由插件
        self.filter_only_router = filter_only_router
        # list
        if circuit_breaker_chain is None:
            self.circuit_breaker_chain = {}
        else:
            self.circuit_breaker_chain = circuit_breaker_chain
        # 负载均衡器
        self.load_balancer = load_balancer
        # 最大重试次数
        self.max_retry_times = max_retry_times
        # 定期检查
        if not check_periods:
            self.check_periods = CheckPeriods()
        else:
            self.check_periods = check_periods
        # 默认API超时时间
        self.default_api_timeout = default_api_timeout
        # 服务器级的均衡器
        if svc_load_balancer_chain is None:
            self.svc_load_balancer_chain = {}
        else:
            self.svc_load_balancer_chain = svc_load_balancer_chain
        # 系统服务列表
        if server_service is None:
            self.server_services = []
        else:
            self.server_services = server_service
        # 服务级的路由责任链
        if svc_to_router_chain is None:
            self.svc_to_router_chain = {}
        else:
            self.svc_to_router_chain = svc_to_router_chain
        # 服务路由责任链
        if router_chain is None:
            self.router_chain = []
        else:
            self.router_chain = router_chain
        # Java 对齐的三段路由链
        self.before_router_chain = [] if before_router_chain is None else before_router_chain
        self.after_router_chain = [] if after_router_chain is None else after_router_chain
        self.global_ctx = global_ctx if global_ctx is not None else ValueContext()
        self.file_cache = file_cache

        # 全局更新任务集
        self.update_task_set = {}
        self._circuit_breaker_timers = {}
        self.skill_flow = None
        self.skill_connector = None
        self.stat_reporter = None

    def set_default_value_for_instances_request(self, req: GetInstancesRequest):
        if req.timeout == 0:
            req.set_timeout(self.default_api_timeout)
        if req.retry_count == 0:
            req.set_retry_count(self.configuration.get_global().get_api().get_max_retry_times())
        return req

    def set_deafult_value_for_reqisgter_request(self, req: InstanceRegisterRequest):
        if req.timeout == 0:
            req.set_timeout(self.default_api_timeout)
        if req.retry_count == 0:
            req.set_retry_count(self.configuration.get_global().get_api().get_max_retry_times())
        return req

    def set_default_value_for_deregister_request(self, req: InstanceDeRegisterRequest):
        if req.timeout == 0:
            req.set_timeout(self.default_api_timeout)
        if req.retry_count == 0:
            req.set_retry_count(self.configuration.get_global().get_api().get_max_retry_times())
        return req

    def set_default_value_for_heartbeat_request(self, req: InstanceHeartbeatRequest):
        if req.timeout == 0:
            req.set_timeout(self.default_api_timeout)
        if req.retry_count == 0:
            req.set_retry_count(self.configuration.get_global().get_api().get_max_retry_times())
        return req

    def set_default_value_for_rule_request(self, req: GetServiceRuleRequest):
        if req.timeout == 0:
            req.set_timeout(self.default_api_timeout)
        if req.retry_count == 0:
            req.set_retry_count(self.configuration.get_global().get_api().get_max_retry_times())
        return req

    def get_router_chain(self, svc: ServiceKey):
        chain = self.svc_to_router_chain.get(svc, None)
        if chain:
            return chain
        else:
            return self.router_chain

    def get_full_router_chain(self, svc: ServiceKey):
        return self.before_router_chain + self.get_router_chain(svc) + self.after_router_chain

    # 获取负载均衡器
    def get_load_balancer(self, svc: ServiceKey):
        return self.svc_load_balancer_chain.get(svc, self.load_balancer)

    # 初始化服务端插件
    def init_server_service_plugins(self, plugins: PluginManager):
        router_list = list()
        for router_name in DefaultConf.DefaultServerServiceRouterChain:
            router = plugins.get_instance(PluginType.SERVICE_ROUTER, router_name)
            router_list.append(router)

        for svc in self.server_services:
            self.svc_to_router_chain[svc.service_key] = router_list
            load_balance = plugins.get_instance(PluginType.LOAD_BALANCE,
                                       DefaultConf.DefaultServerServiceToLoadBalancer[svc.cluster_type])
            self.svc_load_balancer_chain[svc.service_key] = load_balance
        return True

    def instance_request_to_cache_filter(self, req: GetInstancesRequest, redirect_service: ServiceMetadata):
        filters = CacheFilter(namespace=req.get_namespace(), service=req.get_service(),
                              dest_instance_fileter=InstanceFilter(service=req.get_service(),
                                                                   namespace=req.get_namespace(),
                                                                   is_internal_request=False))
        if redirect_service:
            filters = build_redirected_filter(filters, redirect_service)
        return filters

    def create_async_flow_future(self, req: FutureRequest):
        future = AsyncFlowFuture(request=req)
        future.engine = Engine
        return future

    def start_job_thread(self):
        """Start the single event loop used by gRPC and background jobs."""
        if self.thread is not None and self.thread.is_alive():
            logger.warning("sdk has already had a alive thread")
            return

        startup_errors = []

        def run_jobs():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.loop = loop
            try:
                loop.run_until_complete(self.init_self_ip())
                if self.stat_reporter is not None:
                    loop.run_until_complete(self.stat_reporter.start(self))
                logger.warning("start timing update job")
                loop.create_task(self.timing_update_server_task())
                loop.create_task(self.timing_expire_cache_task())
                if self.circuit_breaker_chain:
                    logger.warning("start circuit break job")
                    loop.create_task(self.timing_check_circuit_break_task())
                logger.warning("start job of client reporting")
                loop.create_task(self.add_client_report_task())
                if hasattr(self.svc_connector, "start_address_switching"):
                    self.svc_connector.start_address_switching()
                self._loop_ready.set()
                loop.run_forever()
            except Exception as error:
                startup_errors.append(error)
            finally:
                if startup_errors:
                    self._destroyed = True
                    loop.run_until_complete(self._shutdown())
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.close()
                self.loop = None
                self._finish_destroy()
                self._loop_ready.set()

        def async_job_threading():
            with logger.use_context_logger(self.global_ctx.logger):
                run_jobs()

        self.thread = threading.Thread(target=async_job_threading, daemon=True)
        self.thread.start()
        connect_timeout = self.configuration.get_global().get_server_connector().get_connect_timeout() / 1000
        if not self._loop_ready.wait(timeout=max(5, connect_timeout + 5)):
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "failed to start SDK event loop")
        if startup_errors:
            raise startup_errors[0]

    async def init_self_ip(self):
        """Resolve this context's SDK IP before reporting without changing instance hosts."""
        global_config = self.configuration.get_global()
        api_config = global_config.get_api()
        if api_config.bind_ip or api_config.get_bind_intf():
            return
        api_config.bind_ip_value = ""
        connector = global_config.get_server_connector()
        address = connector.get_addresses()[0]
        try:
            api_config.bind_ip_value = await util.get_local_ip(address, connector.get_connect_timeout())
        except (OSError, ValueError) as error:
            network_logger.warning("failed to resolve SDK bindIP via %s; keeping it empty: %s", address, error)

    def add_destroy_callback(self, callback):
        """Release context-owned resources only after this engine has stopped."""
        self._destroy_callbacks.append(callback)

    def _finish_destroy(self):
        if self._resources_released:
            return
        self._resources_released = True
        if self.skill_flow is not None:
            try:
                self.skill_flow.destroy()
            except Exception:
                cache_logger.error("failed to release Skill backups: %s", traceback.format_exc())
        self.update_task_set.clear()
        for callback in self._destroy_callbacks:
            try:
                callback()
            except Exception:
                with logger.use_context_logger(self.global_ctx.logger):
                    logger.error("failed to release context resources: %s", traceback.format_exc())
        self._destroy_callbacks.clear()

    def _submit(self, coroutine, loop):
        # Bind the task at submission without wrapping an unstarted coroutine.
        with logger.use_context_logger(self.global_ctx.logger):
            return asyncio.run_coroutine_threadsafe(coroutine, loop)

    async def _run_async(self, coroutine: Coroutine[Any, Any, T]) -> T:
        """Run a coroutine on the SDK loop from any caller loop."""
        loop = self.loop
        if self._destroyed or loop is None:
            coroutine.close()
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "SDK engine has been destroyed")
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is loop:
            with logger.use_context_logger(self.global_ctx.logger):
                return await coroutine
        try:
            future = self._submit(coroutine, loop)
        except RuntimeError as error:
            coroutine.close()
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "SDK event loop is unavailable") from error
        return await asyncio.wrap_future(future)

    def _run_sync(self, coroutine: Coroutine[Any, Any, T]) -> T:
        """Block on a coroutine running on the SDK loop."""
        loop = self.loop
        if self._destroyed or loop is None:
            coroutine.close()
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "SDK engine has been destroyed")
        if self.thread is not None and threading.current_thread() is self.thread:
            coroutine.close()
            raise SDKError(ErrorCode.ErrCodeInvalidStateError,
                           "sync API cannot run on the SDK event loop; use the async_ API")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            coroutine.close()
            raise SDKError(ErrorCode.ErrCodeInvalidStateError,
                           "sync API cannot run in an active event loop; use the async_ API")
        try:
            future = self._submit(coroutine, loop)
        except RuntimeError as error:
            coroutine.close()
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "SDK event loop is unavailable") from error
        return future.result()

    async def _shutdown(self):
        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for handle, _, _ in self._circuit_breaker_timers.values():
            handle.cancel()
        self._circuit_breaker_timers.clear()
        await self.register_states.close()
        if self.stat_reporter is not None:
            await self.stat_reporter.close()
        close = getattr(self.svc_connector, "close", None)
        if close is not None:
            await close()
        if self.skill_connector is not None:
            await self.skill_connector.close()

    async def _shutdown_on_loop(self, loop):
        try:
            await self._shutdown()
        finally:
            loop.stop()

    def destroy(self):
        """Stop jobs and close the selected server connector."""
        if self._destroyed:
            return
        self._destroyed = True
        loop = self.loop
        if loop is not None and loop.is_running():
            if threading.current_thread() is self.thread:
                loop.create_task(self._shutdown_on_loop(loop))
                return
            try:
                self._submit(self._shutdown(), loop).result()
            except Exception:
                with logger.use_context_logger(self.global_ctx.logger):
                    network_logger.error("failed to close server connector: %s", traceback.format_exc())
            finally:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(loop.stop)
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join()
        if self.thread is None or not self.thread.is_alive():
            self.loop = None
            self._finish_destroy()

    def sync_get_instances(self, req: GetInstancesRequest, do_balance: bool = True, load: bool = True):
        """Return candidates through the SDK event loop."""
        return self._run_sync(self._query_instances(req, "candidates", load))

    async def async_get_instances(self, req: GetInstancesRequest, do_balance: bool = True,
                                  load: bool = True) -> CacheResult:
        """Asynchronously load all instances through the SDK event loop."""
        return await self._run_async(self._query_instances(req, "candidates", load))

    def sync_get_all_instances(self, req):
        return self._run_sync(self._query_instances(req, "all"))

    async def async_get_all_instances(self, req):
        return await self._run_async(self._query_instances(req, "all"))

    def sync_get_healthy_instances(self, req):
        return self._run_sync(self._query_instances(req, "healthy"))

    async def async_get_healthy_instances(self, req):
        return await self._run_async(self._query_instances(req, "healthy"))

    async def _query_instances(self, req, mode, load=True):
        from polaris.pkg.model.service import InstancesResponse
        result = await self._async_get_instances(req, load=load)
        if result is None or result.dest_instances is None:
            return None
        snapshot = result.dest_instances
        if mode != "all":
            snapshot = self.filter_instances(req, snapshot, healthy_only=mode == "healthy")
        return InstancesResponse(snapshot, req.flow_id)

    async def _async_get_instances(self, req: GetInstancesRequest, do_balance: bool = True,
                                   load: bool = True) -> CacheResult:
        req = self.set_default_value_for_instances_request(req)
        request = self.instance_request_to_cache_filter(req=req, redirect_service=None)
        result = await get_load_cache_values(self.registry, request, load, req.use_discover_cache, req.timeout)
        return result

    def sync_get_one_instance(self, req: GetOneInstanceRequest) -> Instance:
        """Load one instance through the SDK event loop."""
        return self._run_sync(self._async_get_one_instance(req))

    async def async_get_one_instance(self, req: GetOneInstanceRequest) -> Instance:
        """Asynchronously load one instance through the SDK event loop."""
        return await self._run_async(self._async_get_one_instance(req))

    async def _async_get_one_instance(self, req: GetOneInstanceRequest) -> Instance:
        instance_request = GetInstancesRequest(flow_id=req.flow_id, service=req.service, namespace=req.namespace,
                                               timeout=req.timeout, use_discover_cache=req.use_discover_cache,
                                               exclude_offline_service=req.exclude_offline_service)

        cache_result = await self._async_get_instances(instance_request)

        if cache_result is None:
            return None

        return self.choose_instance(req, cache_result.dest_instances,
                                    cache_result.source_route_rule, cache_result.dest_route_rule)

    def choose_instance(self, req, instances, source_route_rule=None, dest_route_rule=None):
        """Apply the configured router chain and load balancer to an instance snapshot."""

        service_instances = self.filter_instances(req, instances)
        result = self.load_balancer.choose_instance(service_instances)
        if result is not None and self.circuit_breaker_chain:
            status = result.get_circuit_breaker_status()
            if status.get_status() == CBStatusEnum.HalfOpen and not status.try_allocate_request():
                candidates = [node for node in service_instances.instances
                              if node is not result and node.is_healthy() and
                              node.get_circuit_breaker_status().is_available()]
                while candidates:
                    service_instances.instances = candidates
                    selected = self.load_balancer.choose_instance(service_instances)
                    if selected is None:
                        break
                    if selected.get_circuit_breaker_status().try_allocate_request():
                        return selected
                    candidates = [node for node in candidates if node is not selected]
                route_logger.warning("all instances unavailable; returning %s:%d without half-open permit",
                                     result.get_host(), result.get_port())
        return result

    def filter_instances(self, req, instances, healthy_only=False):
        """Filter a copied list without balancing or allocating half-open permits."""

        service_instances = copy.copy(instances)
        if getattr(req, "exclude_offline_service", False):
            if service_instances.get_service_status() == ServiceStatus.OFFLINE:
                service_instances.instances = []
                service_instances.total_weight = 0
                return service_instances

        routeInfo = RouteInfo(source_service=req.source_service,
                              dest_service=req,
                              include_unhealthy_instances=getattr(req, "include_unhealthy_instance", False),
                              include_circuitbreak_instances=getattr(req, "include_circuit_break_instances", False),
                              canary=req.canary,
                              metadata=req.get_metadata(),
                              metadata_failover_type=req.get_metadata_failover_type())
        for item in self.get_full_router_chain(ServiceKey(req.namespace, req.service)):
            if (healthy_only or getattr(req, "skip_route_filter", False)) and item in self.router_chain:
                continue
            if not item.enable(routeInfo, service_instances):
                continue
            filter_result = item.get_filtered_instances(route_info=routeInfo, instances=service_instances)
            if filter_result is None:
                return None
            service_instances.instances = filter_result.instances
            if not service_instances.instances:
                break
        return service_instances

    async def _skill_call(self, operation, request):
        if self.skill_flow is None:
            from polaris.pkg.flow.skill import SkillFlow
            self.skill_flow = SkillFlow(
                self.skill_connector, self.configuration.get_ai().get_skill().get_server_connector(),
                self.global_ctx.logger.get_logger("cache"),
            )
        return await getattr(self.skill_flow, operation)(request)

    def sync_skill_call(self, operation, request):
        """Run a blocking Skill operation on the context's owner loop."""
        return self._run_sync(self._skill_call(operation, request))

    async def async_skill_call(self, operation, request):
        """Run a Skill operation on the context's owner loop."""
        return await self._run_async(self._skill_call(operation, request))

    def sync_contract_call(self, operation, request):
        """Run a blocking service-contract operation on the context's owner loop."""
        return self._run_sync(getattr(self.svc_connector, operation)(request))

    async def async_contract_call(self, operation, request):
        """Run a service-contract operation on the context's owner loop."""
        return await self._run_async(getattr(self.svc_connector, operation)(request))

    def sync_register(self, req: InstanceRegisterRequest) -> InstanceRegisterResponse:
        """Register an instance on the SDK event loop."""
        return self._run_sync(self._async_register(req))

    async def async_register(self, req: InstanceRegisterRequest) -> InstanceRegisterResponse:
        """Asynchronously register through the same instance lifecycle flow."""
        return await self._run_async(self._async_register(req))

    async def _do_register(self, req: InstanceRegisterRequest) -> InstanceRegisterResponse:
        return await self.svc_connector.register_instance(req)

    async def _async_register(self, req: InstanceRegisterRequest) -> InstanceRegisterResponse:
        if req.auto_heartbeat and req.ttl is None:
            req.ttl = DefaultHeartbeatTTL
        req.validate()
        snapshot = copy.deepcopy(req)
        async with self.register_states.operation_lock(snapshot):
            response = await self._do_register(snapshot)
            if self._destroyed:
                raise SDKError(ErrorCode.ErrCodeInvalidStateError, "SDK engine has been destroyed")
            req.instance_id = snapshot.instance_id = response.instance_id
            if snapshot.auto_heartbeat:
                await self.register_states.put(snapshot)
            return response

    def sync_deregister(self, req: InstanceDeRegisterRequest) -> None:
        """Deregister an instance on the SDK event loop."""
        return self._run_sync(self._async_deregister(req))

    async def async_deregister(self, req: InstanceDeRegisterRequest) -> None:
        """Asynchronously stop instance tasks and deregister through the SDK loop."""
        return await self._run_async(self._async_deregister(req))

    async def _async_deregister(self, req: InstanceDeRegisterRequest) -> None:
        async with self.register_states.operation_lock(req):
            state_request = await self.register_states.remove(req)
            outgoing = copy.deepcopy(req)
            if state_request is not None:
                outgoing.instance_id = state_request.instance_id
            return await self.svc_connector.deregister_instance(outgoing)

    def sync_heartbeat(self, req: InstanceHeartbeatRequest) -> None:
        """Send an instance heartbeat on the SDK event loop."""
        return self._run_sync(self._async_heartbeat(req))

    async def async_heartbeat(self, req: InstanceHeartbeatRequest) -> None:
        """Asynchronously send an explicit heartbeat through the SDK loop."""
        return await self._run_async(self._async_heartbeat(req))

    async def _async_heartbeat(self, req: InstanceHeartbeatRequest) -> None:
        return await self.svc_connector.heartbeat(req)

    def update_location(self, region: str, zone: str, campus: str):
        self.global_ctx.set_value(NearbyKeyAreaWithCampus, campus)
        self.global_ctx.set_value(NearbyKeyAreaWithRegion, region)
        self.global_ctx.set_value(NearbyKeyAreaWithZone, zone)

    def do_circuit_break_for_service(self, svc: ServiceKey, svc_instances: ServiceInstances, cb_name: str = ""):
        """
        对服务进行熔断判断操作
        :param cb_name:
        :param svc:
        :param svc_instances:
        :return:
        """

        request = ServiceUpdateRequest()
        request.namespace = svc_instances.get_namespace()
        request.service = svc_instances.get_service()
        checked = []
        for name, cb in self.circuit_breaker_chain.items():
            if cb_name and name != cb_name:
                continue
            result = cb.timing_circuit_break(svc_instances.instances)
            for target, nodes in ((CBStatusEnum.Open, result.instance_2_open),
                                  (CBStatusEnum.Closed, result.instance_2_close),
                                  (CBStatusEnum.HalfOpen, result.instance_2_halfopen)):
                for node in nodes:
                    properties = InstanceProperties()
                    properties.service = svc
                    properties.ID = node.get_id()
                    allowance = cb.get_half_open_request_count() if target == CBStatusEnum.HalfOpen else 0
                    properties.properties = {"CircuitBreakerStatus": CircuitBreakerStatus(
                        status=target, ts=result.now, allowed_requests_after_half_open=allowance)}
                    request.properties.append(properties)
                    cb.on_state_change(node)
            checked.append((name, cb))
        if request.properties:
            self.registry.update_instances(request)
        for name, cb in checked:
            for node in svc_instances.instances:
                self._schedule_circuit_break_check(node, name, cb)

    def _schedule_circuit_break_check(self, instance, cb_name, cb):
        if self.loop is None or self._destroyed:
            return
        key = (instance.get_namespace(), instance.get_service(), instance.get_id(), cb_name)
        due = cb.next_check_time(instance)
        existing = self._circuit_breaker_timers.get(key)
        if existing is not None:
            handle, local_value, scheduled_due = existing
            if (due is not None and due == scheduled_due and local_value is instance.get_local_value()
                    and not handle.cancelled()):
                return
            handle.cancel()
            self._circuit_breaker_timers.pop(key, None)
        if due is None:
            return
        local_value = instance.get_local_value()

        def check():
            self._circuit_breaker_timers.pop(key, None)
            if self._destroyed:
                return
            try:
                cached = self.registry.get_instances(InstanceFilter(
                    namespace=key[0], service=key[1], is_internal_request=True))
                if cached is None or cached.get_instance_local_value(key[2]) is not local_value:
                    return
                self.do_circuit_break_for_service(ServiceKey(key[0], key[1]), cached, cb_name)
            except Exception:
                circuitbreaker_logger.error("failed to check instance circuit breaker: %s", traceback.format_exc())

        handle = self.loop.call_later(max(0, due - cb.now()) / 1000, check)
        self._circuit_breaker_timers[key] = (handle, local_value, due)

    def _prune_circuit_breaker_timers(self, service_key, instances=None):
        for key, (handle, local_value, _) in list(self._circuit_breaker_timers.items()):
            if key[:2] != (service_key.namespace, service_key.service):
                continue
            if instances is not None and instances.get_instance_local_value(key[2]) is local_value:
                continue
            handle.cancel()
            self._circuit_breaker_timers.pop(key, None)

    async def process_real_time_task(self, task_data: RealTimeLimitTask):
        service_key = task_data.get_service_key()
        svr_instances = self.registry.get_instances(
            InstanceFilter(service=service_key.get_service(), namespace=service_key.get_namespace(),
                           is_internal_request=True))
        if svr_instances is None or not svr_instances.is_initialized():
            return None
        self.do_circuit_break_for_service(task_data.get_service_key(), svr_instances, task_data.get_cb_name())
        # await self.do_period_task(task_data.get_service_key(), svr_instances)
        return None

    @staticmethod
    def get_now_ts():
        return int(time.time() * 1000)

    # 同步获取服务规则
    async def sync_get_service_rule(self, event_type: int, req: GetServiceRuleRequest) -> ServiceRuleResponse:
        """Load a service rule through the SDK event loop."""
        return await self._run_async(self._get_service_rule(event_type, req))

    async def _get_service_rule(self, event_type: int, req: GetServiceRuleRequest) -> ServiceRuleResponse:
        """Reject non-instance resources until those caches are implemented."""
        del event_type, req
        raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "only instance resources are cached")

    def sync_update_service_call_result(self, req: ServiceCallResult):
        return self._run_sync(self._update_service_call_result(req))

    async def async_update_service_call_result(self, req: ServiceCallResult):
        return await self._run_async(self._update_service_call_result(req))

    async def _update_service_call_result(self, req: ServiceCallResult):
        if self.stat_reporter is not None:
            self.stat_reporter.report(req)
        if not self.circuit_breaker_chain:
            return None
        if req.called_instance is None or req.ret_code is None:
            return None
        svc = ServiceKey(req.get_namespace(), req.get_service())
        cached = self.registry.get_instances(InstanceFilter(
            namespace=svc.namespace, service=svc.service, is_internal_request=True))
        if cached is None or cached.get_instance_local_value(req.get_id()) is not req.called_instance.get_local_value():
            return None
        instance = cached.instances_map[req.get_id()]
        for cb_name, cb in self.circuit_breaker_chain.items():
            ret = cb.realtime_circuit_break(instance, req.get_ret_code(), req.get_delay())
            if ret:
                self.do_circuit_break_for_service(svc, cached, cb_name)
            else:
                self._schedule_circuit_break_check(instance, cb_name, cb)

    async def timing_update_server_task(self):
        while True:
            try:
                network_logger.debug("begin to update server info")
                if not self.update_task_set:
                    continue
                local_update_task_set = self.update_task_set.copy()
                for service_key, update_task in local_update_task_set.items():
                    if update_task.cache_obj.loading or not update_task.need_update():
                        continue
                    if update_task.runner is None or update_task.runner.done():
                        update_task.runner = asyncio.create_task(self._run_service_update_task(update_task))
            except Exception as exception:
                network_logger.error("receive exception when doing periodic server info updating %s", traceback.format_exc())
            finally:
                await asyncio.sleep(self.configuration.get_consumer().local_cache.service_refresh_interval / 1000)

    async def _run_service_update_task(self, task):
        try:
            await self.process_update_task(task)
        except Exception:
            cache_logger.error("failed to refresh resource %s: %s", task.service_key.__dict__, traceback.format_exc())

    async def timing_expire_cache_task(self):
        """Periodically reclaim idle resources independently of pending discovery reads."""
        expire_time = self.configuration.get_consumer().get_local_cache().get_service_expire_time()
        check_interval = min(expire_time / 2, 60 * 60 * 1000) / 1000
        while True:
            await asyncio.sleep(check_interval)
            try:
                await self.registry.expire_services()
            except Exception:
                cache_logger.error("failed to evict idle cache resources: %s", traceback.format_exc())

    async def stop_service_update(self, service_key, cache_obj):
        """Stop the old resource generation before closing its discovery stream."""
        if service_key.event_type == EventType.Instance:
            self._prune_circuit_breaker_timers(service_key)
        task = self.update_task_set.get(service_key)
        if task is not None and task.cache_obj is cache_obj:
            self.update_task_set.pop(service_key)
            if task.runner is not None and task.runner is not asyncio.current_task() and not task.runner.done():
                task.runner.cancel()
                await asyncio.gather(task.runner, return_exceptions=True)
        request = InstanceDiscoverRequest(1, service_key.service, service_key.namespace)
        try:
            await self.svc_connector.stop_discover(request)
        finally:
            await self.file_cache.delete(request)

    def _service_update_active(self, task):
        return self.update_task_set.get(task.service_key) is task and not task.cache_obj.invalid

    async def timing_check_circuit_break_task(self):
        while True:
            try:
                circuitbreaker_logger.debug("begin to do circuit break task")
                services = self.registry.get_services()
                for service_key, v in services.items():
                    if service_key.event_type != EventType.Instance:
                        continue
                    svr_instances = self.registry.get_instances(
                        InstanceFilter(service=service_key.get_service(), namespace=service_key.get_namespace(),
                                       is_internal_request=True))
                    if svr_instances is None or not svr_instances.is_initialized():
                        continue
                    self.do_circuit_break_for_service(service_key, svr_instances)
            except Exception as e:
                circuitbreaker_logger.error("receive exception when doing circuit break checking %s", traceback.format_exc())
            finally:
                await asyncio.sleep(self.configuration.get_consumer().circuit_breaker.check_period / 1000)

    async def process_update_task(self, task: ServiceUpdateTask):
        if not self._service_update_active(task) or task.cache_obj.loading or not task.need_update():
            return

        revision = self.registry.get_service_revision(task.service_key.service, task.service_key.namespace,
                                                      task.service_key.event_type)
        if task.service_key.event_type != EventType.Instance:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "only instance resources are cached")
        request = InstanceDiscoverRequest(type=1, name=task.service_key.service,
                                          namespace=task.service_key.namespace, revision=revision)

        client = self.svc_connector

        def get_local_value_func(ins):
            cached = task.cache_obj.value
            local_value = cached.get_instance_local_value(ins.get_id()) if cached is not None else None
            if local_value is None:
                return DefaultInstanceLocalValue()
            else:
                return local_value

        for _ in range(self.configuration.get_global().get_api().max_retry_times):
            if not self._service_update_active(task):
                return
            try:
                ret = await client.discover(request)
                if not self._service_update_active(task):
                    return

                service_ins = ServiceInstances.new_from_discover_rsp(ret, get_local_value_func)
                if (task.cache_obj.value is not None and not task.cache_obj.value.loaded_from_file
                        and task.cache_obj.value.revision == service_ins.revision):
                    task.last_update_time = int(time.time() * 1000)
                    break
                self._prune_circuit_breaker_timers(task.service_key, service_ins)
                cache_logger.warning("get instance update %s %s %s", task.service_key.__dict__,
                               len(service_ins.instances),
                               service_ins.filtered_instances.__dict__)

                # for k, v in self.registry.service_map.items():
                #     print(k.service, v.value.instances)
                update_ret = self.registry.update_service(task.service_key, service_ins)
                if update_ret is False:
                    cache_logger.error("Failed to update service %s", task.service_key.__dict__)
                    break
                self.file_cache.save(request, ret)
                task.last_update_time = int(time.time() * 1000)

            except SDKError as err:
                if not self._service_update_active(task):
                    return
                if err.server_code == ServerCode.NotFoundService:
                    async with task.cache_obj.load_lock:
                        await self.registry.remove_service(task.service_key, task.cache_obj)
                    return
                if err.err_code == ErrorCode.ErrCodeDataNotChange:
                    task.cache_obj.remote_updated = True
                    task.last_update_time = int(time.time() * 1000)
                    cache_logger.info("Data not change for updating %s", task.service_key.__dict__)
                    break
                cache_logger.error("Failed to discover %s in periodic updating task because %s", task.service_key.__dict__,
                             repr(err))
                continue
            else:
                cache_logger.warning("success to update %s", task.service_key.__dict__)
                break
        return

    def load_local_client_report_result(self):
        resp = response_pb2.Response()
        # TODO load from local cache file

    async def add_client_report_task(self):
        values = ValueContext()
        while True:
            try:
                await self.do_period_client_report(values)
            except Exception as exception:
                stat_report_logger.error("receive exception when add client report task %s", traceback.format_exc())
            finally:
                await asyncio.sleep(UPDATE_INTERVAL)

    async def do_period_client_report(self, ctx_values: ValueContext):
        now = time.time()
        if keyLastClientReportTimes in ctx_values.core_map:
            last_report_time_value = ctx_values.get_value(keyLastClientReportTimes)
            if (now - last_report_time_value) * 1000 < self.check_periods.client_report:
                return
        ctx_values.set_value(keyLastClientReportTimes, now)
        api_config = self.configuration.get_global().get_api()
        client_host = api_config.get_bind_ip()

        report_client_req = ReportClientRequest(
            version=version,
            client_id=self.global_ctx.get_client_id(),
            timeout=self.default_api_timeout,
            # TODO
            persist_handler=None
        )

        if len(client_host) > 0:
            report_client_req.host = client_host

        if self.stat_reporter is not None:
            info = self.stat_reporter.meta_info()
            if info is not None:
                report_client_req.reporter_meta_infos = [info]

        report_client_resp = await self.svc_connector.report_client(report_client_req)

        self.update_location(
            region=report_client_resp.region,
            zone=report_client_resp.zone,
            campus=report_client_resp.campus
        )

def build_instance_property(now, allowed_request: int, request: ServiceUpdateRequest, cb_name: str):
    property = InstanceProperties()
    property.set_id()


def build_redirected_filter(filters: CacheFilter, redirect_service: ServiceMetadata):
    filters.service = redirect_service.get_service()
    filters.namespace = redirect_service.get_namespace()
    filters.desc_instances_filter.service = redirect_service.get_service()
    filters.desc_instances_filter.namespace = redirect_service.get_namespace()
    return filters


def build_service_update_request(svc: ServiceKey, results: Dict[str, CircuitBreakResult]):
    request = ServiceUpdateRequest(namespace=svc.get_namespace(), service=svc.get_service())
    for cb_name, result in results.items():
        build_instance_property(result.instance_2_close, result)

    return None


def create_flow_engine(config: Configuration, plugins: PluginManager, global_ctx: ValueContext) -> Engine:
    if global_ctx is None:
        global_ctx = ValueContext()

    setup(InitContext(value_ctx=global_ctx, config=config, plugins=plugins))

    flow_engine = Engine(config=config, default_api_timeout=config.get_global().get_api().get_timeout(),
                         global_ctx=global_ctx, file_cache=plugins.get_instance(PluginType.LOCAL_CACHE, "file"),
                         server_service=list(get_server_services(config).values()))
    try:
        return _initialize_flow_engine(flow_engine, config, plugins, global_ctx)
    except Exception:
        flow_engine.destroy()
        raise


def _initialize_flow_engine(flow_engine, config, plugins, global_ctx):
    protocol = config.get_global().get_server_connector().get_protocol()

    # 加载服务端连接器
    target_plugin = plugins.get_instance(PluginType.SERVER_CONNECTOR, protocol)
    flow_engine.svc_connector = target_plugin
    flow_engine.skill_connector = plugins.get_instance(PluginType.SKILL_CONNECTOR, "polaris")
    flow_engine.stat_reporter = plugins.get_instance(PluginType.STAT_REPORTER, "prometheus")
    if hasattr(flow_engine.svc_connector, "connection"):
        flow_engine.svc_connector.connection.stat_reporter = flow_engine.stat_reporter
        flow_engine.svc_connector.engine = flow_engine

    # 加载本地缓存
    local_cache_type = config.get_consumer().get_local_cache().get_type()
    target_plugin = plugins.get_instance(PluginType.LOCAL_CACHE, local_cache_type)
    flow_engine.registry = target_plugin

    # 加载注册中心服务地址依赖插件
    ret = flow_engine.init_server_service_plugins(plugins)
    if not ret:
        # TODO
        # raise Error
        return None

    # 加载 Java 对齐的 before / core / after 三段服务路由链
    router_config = config.get_consumer().get_service_router()
    for config_field, engine_field in (
            ("before_chain", "before_router_chain"),
            ("chain", "router_chain"),
            ("after_chain", "after_router_chain")):
        routers = [plugins.get_instance(PluginType.SERVICE_ROUTER, router_name)
                   for router_name in getattr(router_config, "get_%s" % config_field)()]
        setattr(flow_engine, engine_field, routers)

    # 加载负载均衡插件
    load_balance_type = config.get_consumer().get_load_balancer().get_type()
    target_plugin = plugins.get_instance(PluginType.LOAD_BALANCE, load_balance_type)
    flow_engine.load_balancer = target_plugin

    # 加载全局上下文
    flow_engine.global_ctx = global_ctx

    # 加载客户端本地信息
    flow_engine.load_local_client_report_result()
    # 添加客户端定期上报任务
    flow_engine.check_periods.client_report = config.get_global().get_api().get_report_interval()

    # 加载熔断器组件
    cb_config = config.get_consumer().get_circuit_breaker()
    enable_cb = cb_config.is_enable() and cb_config.is_default_rule_enable()
    if enable_cb:
        cb_chain = config.get_consumer().get_circuit_breaker().get_chain()
        if len(cb_chain) > 0:
            for cb_name in cb_chain:
                target_plugin = plugins.get_instance(PluginType.CIRCUIT_BREAKER, cb_name)
                # print("polaris CIRCUIT_BREAKER plugin", target_plugin)
                flow_engine.circuit_breaker_chain[cb_name] = target_plugin

    global_ctx.set_value(ContextKeyEngine, flow_engine)
    logger.info("success to start polaris engine")
    flow_engine.start_job_thread()
    return flow_engine
