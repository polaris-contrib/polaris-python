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

import time
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2
from polaris.pkg.model import core
from typing import Dict, List
from polaris.pkg.model.error import SDKError, ErrorCode
from polaris.pkg.config.default import DefaultConf
from .stat import SlidingWindow


class RunMode:
    ModeNoAgent = 0
    ModeWithAgent = 1


# ServiceMetadata 服务元数据信息
class ServiceMetadata:
    def __init__(self, service: service_pb2.Service):
        self.service = service

    # 获取服务名
    def get_service(self):
        return self.service.name.value

    # 获取命名空间
    def get_namespace(self):
        return self.service.namespace.value

    # 获取元数据信息
    def get_metadata(self):
        return self.service.metadata

    def get_service_type(self):
        """Return the registry service category without changing its instance type."""
        return self.service.service_type if self.service is not None else ServiceType.MICROSERVICE

    def get_service_status(self):
        """Return the registry lifecycle status of this service."""
        return self.service.service_status if self.service is not None else ServiceStatus.NORMAL

    def get_extended_metadata(self):
        """Return typed service metadata, including mounted skills."""
        if self.service is None:
            return []
        return [ExtendedMetadata(
            type=item.type,
            agent_skill=AgentSkill(
                id=item.agent_skill.id, name=item.agent_skill.name,
                description=item.agent_skill.description, version=item.agent_skill.version,
                tags=list(item.agent_skill.tags), examples=list(item.agent_skill.examples),
                input_modes=list(item.agent_skill.input_modes), output_modes=list(item.agent_skill.output_modes),
            ) if item.HasField("agent_skill") else None,
        ) for item in self.service.extended_metadata]


class ServiceType(IntEnum):
    """Service categories defined by Polaris."""

    MICROSERVICE = service_pb2.SERVICE_TYPE_MICROSERVICE
    MCP_SERVER = service_pb2.SERVICE_TYPE_MCP_SERVER
    AI_AGENT = service_pb2.SERVICE_TYPE_AI_AGENT


class ServiceStatus(IntEnum):
    """Service lifecycle states defined by Polaris."""

    NORMAL = service_pb2.NORMAL
    ABNORMAL = service_pb2.ABNORMAL
    OFFLINE = service_pb2.OFFLINE


@dataclass
class AgentSkill:
    """A skill mounted on a registry service."""

    id: str = ""
    name: str = ""
    description: str = ""
    version: str = ""
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    input_modes: list[str] = field(default_factory=list)
    output_modes: list[str] = field(default_factory=list)


@dataclass
class ExtendedMetadata:
    """Typed extended metadata returned with a service snapshot."""

    SKILL = service_pb2.ExtendedMetadata.EXTENDED_METADATA_SKILL
    type: int = 0
    agent_skill: AgentSkill | None = None


# 断路器状态
class CBStatusEnum:
    # 断路器已打开，代表节点已经被熔断
    Open = 0
    # 断路器半开，节点处于刚熔断恢复，只允许少量请求通过
    HalfOpen = 1
    # 断路器关闭，节点处于正常工作状态
    Closed = 2


# 熔断器状态管理器
class CircuitBreakerStatus:
    def __init__(self, status: int = CBStatusEnum.Closed, ts: int = 0, requests_after_half_open: int = 0,
                 allowed_requests_after_half_open: int = 0):
        self.lock = threading.RLock()
        self.status = status
        self.ts = ts  # start time
        self.requests_after_half_open = requests_after_half_open
        self.allowed_requests_after_half_open = allowed_requests_after_half_open
        self.successful_requests_after_half_open = 0
        self.failed_requests_after_half_open = 0

    # 熔断状态
    def get_status(self):
        with self.lock:
            return self.status

    # 状态转换的时间
    def get_start_time(self):
        with self.lock:
            return self.ts

    # TODO
    # 半开状态后已分配的请求数
    def get_request_count_after_half_open(self):
        with self.lock:
            return self.requests_after_half_open

    # 尝试分配请求
    def try_allocate_request(self):
        with self.lock:
            if self.status == CBStatusEnum.Closed:
                return True
            if self.status == CBStatusEnum.Open:
                return False
            if self.requests_after_half_open >= self.allowed_requests_after_half_open:
                return False
            self.requests_after_half_open += 1
            return True

    def report_half_open_result(self, success: bool):
        with self.lock:
            if success:
                self.successful_requests_after_half_open += 1
            else:
                self.failed_requests_after_half_open += 1

    # 是否可以分配请求
    def is_available(self):
        with self.lock:
            if self.status == CBStatusEnum.Closed:
                return True
            if self.status == CBStatusEnum.Open:
                return False
            if self.requests_after_half_open >= self.allowed_requests_after_half_open:
                return False
            return True


class InstanceWeight:
    def __init__(self, instance_id: str, dynamic_weight: int):
        self.instance_id = instance_id
        self.dynamic_weight = dynamic_weight


class InstanceLocalValue:
    def get_circuit_breaker_status(self) -> CircuitBreakerStatus:
        raise Exception("[InstanceLocalValue] get_circuit_breaker_status not implemented")

    def set_circuit_breaker_status(self, status: CircuitBreakerStatus):
        raise Exception("[InstanceLocalValue] set_circuit_breaker_status not implemented")


class DefaultInstanceLocalValue(InstanceLocalValue):
    def __init__(self):
        # TODO window是在cb里进行设置的，因为cb知道window的参数
        self.window = None
        self.circuit_breaker_metrics = None
        self.cb_status = CircuitBreakerStatus()

    # TODO
    def get_sliding_window(self, bucket_count=2, bucket_interval=60000):
        if self.window is None:
            self.window = SlidingWindow(bucket_count, bucket_interval)
        return self.window

    def set_sliding_window(self, sliding_window):
        self.window = sliding_window

    def get_circuit_breaker_status(self) -> CircuitBreakerStatus:
        return self.cb_status

    def set_circuit_breaker_status(self, cb: CircuitBreakerStatus):
        self.cb_status = cb


def create_default_instance_local_value(inst_id: str) -> InstanceLocalValue:
    return DefaultInstanceLocalValue()


# 服务实例信息
class Instance:
    def __init__(self, instance: service_pb2.Instance, service_key: core.ServiceKey,
                 local_value: InstanceLocalValue = None):
        self.instance = instance
        self.service_key = service_key
        self.local_value: InstanceLocalValue = local_value if local_value is not None else DefaultInstanceLocalValue()

    # 实例所在命名空间
    def get_namespace(self):
        return self.service_key.namespace

    # 实例所在服务名
    def get_service(self):
        return self.service_key.service

    # 服务实例唯一标识
    def get_id(self):
        return self.instance.id.value

    # 实例的域名/IP信息
    def get_host(self):
        return self.instance.host.value

    # 实例Revision
    def get_revision(self):
        return self.instance.revision.value

    # 实例的监听端口
    def get_port(self):
        return self.instance.port.value

    # 服务实例的协议
    def get_protocol(self):
        return self.instance.protocol.value

    # 实例版本号
    def get_version(self):
        return self.instance.version.value

    # 实例静态权重值
    def get_weight(self):
        return self.instance.weight.value if self.instance.HasField("weight") else 100

    # 实例优先级信息
    def get_priority(self):
        return self.instance.priority.value

    # 实例逻辑分区
    def get_logicset(self):
        return self.instance.logic_set.value

    # 实例的断路器状态，包括：
    # 打开（被熔断）、半开（探测恢复）、关闭（正常运行）
    def get_circuit_breaker_status(self) -> CircuitBreakerStatus:
        return self.local_value.get_circuit_breaker_status()

    # TODO
    def get_sliding_window(self, bucket_count=10, bucket_interval=6000) -> SlidingWindow:
        return self.local_value.get_sliding_window(bucket_count, bucket_interval)

    # 实例是否健康，基于服务端返回的健康数据
    def is_healthy(self):
        return self.instance.healthy.value

    # 实例是否已经被手动隔离
    def is_isolated(self):
        return self.instance.isolate.value

    # 实例是否启动了健康检查
    def is_enable_healthcheck(self):
        return self.instance.HasField("health_check")

    # 实例所属的大区信息
    def get_region(self):
        if not self.instance.location:
            return ""
        return self.instance.location.region.value

    # 实例所属的地方信息
    def get_zone(self):
        if not self.instance.location:
            return ""
        return self.instance.location.zone.value

    # 实例所属的IDC信息
    def get_idc(self):
        if not self.instance.location:
            return ""
        return self.instance.location.campus.value

    # 实例所属的IDC信息
    def get_campus(self):
        if not self.instance.location:
            return ""
        return self.instance.location.campus.value

    def get_local_value(self) -> InstanceLocalValue:
        return self.local_value

    def get_metadata(self):
        return self.instance.metadata


# 服务路由实例过滤计算
class RouteFilterCounter:
    def __init__(self, value: int = 0):
        self.value = value

    # 增加偏移值
    def add_value(self, diff):
        self.value += diff

    # 获取过滤值
    def get_value(self):
        return self.value


class FilteredInstanceCounter:
    def __init__(self):
        self.isolated_instances = 0
        self.unhealthy_instances = 0
        self.route_filter_counters = {}

    def add_isolated_instances(self, n: int):
        self.isolated_instances += n

    def get_isolated_instances(self):
        return self.isolated_instances

    def add_unhealthy_instances(self, n: int):
        self.unhealthy_instances += n

    def get_unhealthy_instances(self):
        return self.unhealthy_instances

    def add_route_filter_instances(self, router_name: str, n: int):
        if router_name in self.route_filter_counters:
            self.route_filter_counters[router_name].add_value(n)
        self.route_filter_counters[router_name] = RouteFilterCounter(n)

    def get_route_filter_instances(self, router_name: str):
        if router_name in self.route_filter_counters:
            return self.route_filter_counters[router_name].get_value()
        return 0


# 服务信息
class ServiceInstances(ServiceMetadata):
    def __init__(self, service: service_pb2.Service = None, instances: List[Instance] = None,
                 filtered_instances: FilteredInstanceCounter = None, instances_map=None,
                 initialized: bool = True, total_weight: int = 0, revision: str = "",
                 loaded_from_file: bool = False):
        super().__init__(service)
        self.filtered_instances = filtered_instances
        if instances is None:
            self.instances = []
        else:
            self.instances: List[Instance] = instances
        if instances_map is None:
            self.instances_map: Dict[str, Instance] = {}
        else:
            self.instances_map: Dict[str, Instance] = instances_map
        self.total_weight = total_weight
        self.initialized = initialized
        self.revision = revision
        self.loaded_from_file = loaded_from_file

    @classmethod
    def new_from_discover_rsp(cls, resp: response_pb2.DiscoverResponse, get_local_value_func=None,
                             old_instances=None, loaded_from_file=False):
        if resp is None:
            return ServiceInstances()

        snapshot = response_pb2.DiscoverResponse()
        snapshot.CopyFrom(resp)
        service_instances = ServiceInstances(service=snapshot.service,
                                             instances=[],
                                             filtered_instances=FilteredInstanceCounter(),
                                             instances_map={},
                                             initialized=True, loaded_from_file=loaded_from_file)
        service_instances.revision = resp.service.revision.value

        svc_key = core.ServiceKey(resp.service.namespace.value, resp.service.name.value)

        for ins in snapshot.instances:
            instance = Instance(ins, svc_key)
            local_value = old_instances.get_instance_local_value(instance.get_id()) if old_instances else None
            if local_value is None and get_local_value_func is not None:
                local_value = get_local_value_func(instance)
            if local_value is not None:
                instance.local_value = local_value

            service_instances.total_weight += instance.get_weight()
            service_instances.instances.append(instance)
            service_instances.instances_map[instance.get_id()] = instance

        service_instances.instances.sort(key=lambda instance: (instance.get_host(), instance.get_port()))
        return service_instances

    def is_loaded_from_file(self):
        """Report whether this snapshot came from a persisted discover response."""
        return self.loaded_from_file

    # 返回实例的id集合
    def get_svc_id_set(self):
        return self.instances_map.keys()

    # 获取服务名
    def get_service(self) -> str:
        return self.service.name.value if self.service is not None else ""

    # 获取名字空间
    def get_namespace(self) -> str:
        return self.service.namespace.value if self.service is not None else ""

    # 获取元数据信息
    def get_metadata(self):
        return self.service.metadata if self.service is not None else {}

    # 获取服务实例列表
    def get_instances(self) -> List[Instance]:
        return self.instances

    def get_revision(self):
        return self.revision

    def get_total_weight(self):
        return self.total_weight

    def get_filter_instance_counter(self) -> FilteredInstanceCounter:
        return self.filtered_instances

    def get_instance_local_value(self, id: str) -> InstanceLocalValue:
        if id not in self.instances_map:
            return None
        return self.instances_map[id].get_local_value()

    def is_initialized(self):
        return self.initialized


# 初始化service_instances
def new_service_instances(resp: response_pb2.DiscoverResponse) -> ServiceInstances:
    return ServiceInstances.new_from_discover_rsp(resp)


# 服务信息
class ServiceInfo(ServiceMetadata):
    def __init__(self, service: str = "", namespace: str = "", metadata: Dict[str, str] = None):
        super().__init__(service)
        self.namespace = namespace
        if metadata is None:
            self.metadata = {}
        else:
            self.metadata = metadata

    # 获取服务名
    def get_service(self):
        return self.service

    # 获取命名空间
    def get_namespace(self):
        return self.namespace

    # 获取元数据信息
    def get_metadata(self):
        return self.metadata


# 单个服务实例查询请求
class GetOneInstanceRequest:
    def __init__(self, flow_id: int = 0, service: str = "", namespace: str = "", timeout: int = 0,
                 retry_count: int = 0, source_service: ServiceInfo = None, hash_value: int = 0,
                 use_discover_cache: bool = True, canary: str = "", metadata=None,
                 metadata_failover_type: str = None, exclude_offline_service: bool = False):
        # 可选，流水号
        if metadata is None:
            metadata = {}
        self.flow_id = flow_id
        # 必选，服务名
        self.service = service
        # 必选，命名空间
        self.namespace = namespace
        # 可选，超时时间
        self.timeout = timeout
        # 可选，超时重试次数
        self.retry_count = retry_count
        # 主调方服务信息
        self.source_service = source_service
        # 用于一致性hash的负载均衡
        self.hash_value = hash_value
        # direct
        self.use_discover_cache = use_discover_cache
        # 金丝雀
        self.canary = canary
        # metadata
        self.metadata = metadata
        # none / all / others；None 表示使用服务或插件配置
        self.metadata_failover_type = metadata_failover_type
        # 可选，显式排除 OFFLINE 服务；默认保持完整发现结果
        self.exclude_offline_service = exclude_offline_service

    # 设置超时时间
    def set_timeout(self, timeout: int):
        self.timeout = timeout

    # 设置重试次数
    def set_retrycount(self, retry_count: int):
        self.retry_count = retry_count

    # 获取服务名
    def get_service(self):
        return self.service

    # 获取命名空间
    def get_namespace(self):
        return self.namespace

    def get_metadata(self):
        return self.metadata

    def get_metadata_failover_type(self):
        return self.metadata_failover_type

    def validate(self):
        _validate_instance_query(self)
        if self.source_service is not None:
            validate_service_metadata(self.source_service)
        if self.metadata_failover_type not in (None, "none", "all", "others"):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "metadata_failover_type must be one of none, all, others")
        if type(self.exclude_offline_service) is not bool:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "exclude_offline_service must be boolean")


# 批量服务实例查询请求
class GetInstancesRequest:
    def __init__(self, flow_id: int = 0, service: str = "", namespace: str = "", timeout: int = 0,
                 source_service: ServiceInfo = None, retry_count: int = 0, skip_route_filter: bool = False,
                 include_circuit_break_instances=False,
                 include_unhealthy_instance=False,
                 use_discover_cache: bool = True, metadata=None, metadata_failover_type=None, canary="",
                 exclude_offline_service: bool = False):
        # 可选，流水号，用于跟踪用户的请求，默认0
        self.flow_id = flow_id
        # 必选，服务名
        self.service = service
        # 必选，命名空间
        self.namespace = namespace
        # 主调方信息
        self.source_service = source_service
        # 可选，是否包含被熔断的服务实例，默认false
        self.include_circuit_break_instances = include_circuit_break_instances
        # 可选，是否包含不健康的服务实例，默认false
        self.include_unhealthy_instance = include_unhealthy_instance
        # 可选，是否排除 OFFLINE 服务；get_all_instances 始终返回完整快照
        self.exclude_offline_service = exclude_offline_service
        # 可选，是否跳过服务路由筛选，默认false
        self.skip_route_filter = skip_route_filter
        # 可选，单次查询超时时间，默认直接获取全局的超时配置
        # 用户总最大超时时间为(1+RetryCount) * Timeout
        self.timeout = timeout
        # 可选，重试次数
        self.retry_count = retry_count
        # direct
        self.use_discover_cache = use_discover_cache
        self.metadata = {} if metadata is None else metadata
        self.metadata_failover_type = metadata_failover_type
        self.canary = canary

    def get_metadata(self):
        return self.metadata

    def get_metadata_failover_type(self):
        return self.metadata_failover_type

    def set_timeout(self, timeout: int):
        self.timeout = timeout

    def set_retry_count(self, retry_count: int):
        self.retry_count = retry_count

    def get_service(self):
        return self.service

    def get_namespace(self):
        return self.namespace

    def validate(self):
        _validate_instance_query(self)
        if self.source_service is not None:
            validate_service_metadata(self.source_service)
        for name in ("skip_route_filter", "include_circuit_break_instances", "include_unhealthy_instance",
                     "exclude_offline_service"):
            if type(getattr(self, name)) is not bool:
                raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, f"{name} must be boolean")


class GetAllInstancesRequest(GetInstancesRequest):
    """Fetch the complete instance snapshot without local routing filters."""


class GetHealthyInstancesRequest(GetInstancesRequest):
    """Apply only isolation and recovery filters, including circuit-open nodes by default."""

    def __init__(self, *args, include_circuit_break_instances=True, **kwargs):
        super().__init__(*args, include_circuit_break_instances=include_circuit_break_instances, **kwargs)


class InstancesResponse(ServiceInstances):
    """Expose an independent list and service metadata for one discovery query."""

    def __init__(self, snapshot: ServiceInstances, flow_id=0):
        super().__init__(service=snapshot.service, instances=list(snapshot.instances),
                         filtered_instances=snapshot.filtered_instances,
                         instances_map={node.get_id(): node for node in snapshot.instances},
                         total_weight=sum(node.get_weight() for node in snapshot.instances),
                         revision=snapshot.revision, loaded_from_file=snapshot.loaded_from_file)
        self.flow_id = flow_id


def _validate_instance_query(request):
    for name in ("namespace", "service"):
        if not isinstance(getattr(request, name), str) or not getattr(request, name).strip():
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, f"{name} must be nonempty")
    if type(request.timeout) is not int or request.timeout < 0:
        raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "timeout must be nonnegative milliseconds")
    if type(request.use_discover_cache) is not bool:
        raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "use_discover_cache must be boolean")
    if request.metadata_failover_type not in (None, "none", "all", "others"):
        raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "invalid metadata_failover_type")
    if (not isinstance(request.metadata, dict)
            or any(not isinstance(key, str) or not isinstance(value, str)
                   for key, value in request.metadata.items())):
        raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "metadata must contain string keys and values")


class InstancesFuture:
    def is_done(self):
        pass

    def get(self) -> InstancesResponse:
        pass


class RetStatus:
    RetUnknown = 0
    RetSuccess = 1
    RetFail = 2
    RetTimeout = 3
    RetReject = 4
    RetFlowControl = 5

    descriptions = {0: "unknown", 1: "success", 2: "fail", 3: "timeout", 4: "reject", 5: "flow_control"}


class InstanceType:
    """Metric instance categories shared with Java InstanceType."""

    MICROSERVICE = "microservice"
    MCP = "mcp"
    A2A = "a2a"


class APICallResult:
    def __init__(self, api_name: str, ret_status: int, ret_code: int, delay: int):
        self.api_name = api_name
        self.ret_status = ret_status
        self.ret_code = ret_code
        self.delay = delay


class ServiceCallResult:
    """Report one invocation using an instance or an explicit service endpoint."""

    def __init__(self, called_instance: Instance = None, ret_status: int = RetStatus.RetUnknown,
                 ret_code: int = None, delay: int = None, *, method: str = None,
                 caller_service: ServiceInfo = None, caller_ip: str = None, labels: str = None,
                 instance_type: str = InstanceType.MICROSERVICE, namespace: str = "",
                 service: str = "", host: str = "", port: int = 0):
        self.called_instance = called_instance
        self.ret_status = ret_status
        self.ret_code = ret_code
        self.delay = delay
        self.method = method
        self.caller_service = caller_service
        self.caller_ip = caller_ip
        self.labels = labels
        self.instance_type = instance_type
        self.namespace, self.service, self.host, self.port = namespace, service, host, port

    # 设置返回状态
    def set_ret_status(self, ret_status: int):
        self.ret_status = ret_status

    # 设置实例
    def set_called_instance(self, instance: Instance):
        self.called_instance = instance

    # 实例所属服务名
    def get_service(self) -> str:
        return self.called_instance.get_service() if self.called_instance is not None else self.service

    # 实例所属命名空间
    def get_namespace(self) -> str:
        return self.called_instance.get_namespace() if self.called_instance is not None else self.namespace

    # 实例ID
    def get_id(self):
        return self.called_instance.get_id() if self.called_instance is not None else ""

    # 实例的节点信息
    def get_host(self):
        return self.called_instance.get_host() if self.called_instance is not None else self.host

    # 实例的端口信息
    def get_port(self):
        return self.called_instance.get_port() if self.called_instance is not None else self.port

    # 实例的返回码
    def get_ret_code(self) -> int:
        return self.ret_code

    # 设置实例返回码
    def set_ret_code(self, value: int):
        self.ret_code = value

    # 调用时延
    def get_delay(self) -> int:
        return self.delay

    # 设置时延
    def set_delay(self, delay: int):
        self.delay = delay

    def get_ret_status(self) -> int:
        return self.ret_status

    def get_api(self):
        return self.method or ""

    def get_method(self):
        """Return the invoked method or HTTP path, not the HTTP verb."""
        return self.method

    def set_method(self, method):
        """Assign the invoked method or path."""
        self.method = method

    def validate(self):
        if self.called_instance is not None and not isinstance(self.called_instance, Instance):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "called_instance must be an Instance")
        if self.called_instance is None and (not self.namespace or not self.service or not self.host):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ServiceCallResult: provide an instance or namespace/service/host")
        if type(self.ret_status) is not int or self.ret_status not in RetStatus.descriptions:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ServiceCallResult: invalid retStatus")
        if self.instance_type not in (InstanceType.MICROSERVICE, InstanceType.MCP, InstanceType.A2A):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "ServiceCallResult: invalid instanceType")
        if self.delay is not None and (type(self.delay) is not int or self.delay < 0):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "ServiceCallResult: delay must be nonnegative ms")
        if self.ret_code is not None and type(self.ret_code) is not int:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "ServiceCallResult: retCode must be integer")
        for key in ("method", "caller_ip", "labels"):
            if getattr(self, key) is not None and not isinstance(getattr(self, key), str):
                raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, f"ServiceCallResult: {key} must be string")
        if self.caller_service is not None and not isinstance(self.caller_service, ServiceInfo):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "caller_service must be ServiceInfo")
        if self.called_instance is None and (type(self.port) is not int or not 0 <= self.port <= 65535):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "port must be 0..65535")


def validate_service_metadata(svc_meta: ServiceMetadata):
    if len(svc_meta.get_service()) == 0:
        raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "validate_service_metadata: service is empty")
    if len(svc_meta.get_namespace()) == 0:
        raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "validate_service_metadata: namespace is empty")
    if len(svc_meta.get_metadata()) > 0:
        for k, v in svc_meta.get_metadata().items():
            if len(k) == 0 or len(v) == 0:
                raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                               "validate_service_metadata: metadata has empty key or value")


def is_instance_available(ins: Instance):
    if not ins.is_healthy():
        return False
    cb_status = ins.get_circuit_breaker_status()
    if cb_status is not None and not cb_status.is_available():
        return False
    return True
