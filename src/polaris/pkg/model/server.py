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

from polaris.pkg.model.error import SDKError, ErrorCode
from typing import Dict


#  InstanceDeRegisterRequest 反注册服务请求
class InstanceDeRegisterRequest:
    def __init__(self, service: str, service_token: str, namespace: str, host: str, port: int, instance_id: str = '',
                 timeout: int = 0, retry_count: int = 0):
        # 服务名
        self.service = service
        # 服务访问Token
        self.service_token = service_token
        # 命名空间
        self.namespace = namespace
        # 服务实例ID
        self.instance_id = instance_id
        # 服务实例ip
        self.host = host
        # 服务实例端口
        self.port = port
        # 可选，单次查询超时时间，默认直接获取全局的超时配置
        # 用户总最大超时时间为(1+RetryCount) * Timeout
        self.timeout = timeout
        # 可选，重试次数，默认直接获取全局的超时配置
        self.retry_count = retry_count

    def set_timeout(self, timeout: int):
        self.timeout = timeout

    def set_retry_count(self, retry_count: int):
        self.retry_count = retry_count

    # 验证request是否合理，返回SDKERROR
    def validate(self):
        if len(self.service_token) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceDeRegisterRequest: serviceToken should not be empty")
        if len(self.instance_id) > 0:
            return
        if len(self.service) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceDeRegisterRequest: serviceName should not be empty when instanceId is empty")
        if len(self.namespace) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceDeRegisterRequest: namespace should not be empty when instanceId is empty")
        if len(self.host) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceDeRegisterRequest: host should not be empty when instanceId is empty")
        if self.port <= 0 or self.port >= 65536:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceDeRegisterRequest: port should be in range (0, 65536)")


# 最小权重值
MinWeight = 0
# 最大权重值
MaxWeight = 10000
# 最小优先级
MinPriority = 0
# 最大优先级
MaxPriority = 9
# 健康检查类型：心跳
HealthCheckTypeHeartBeat = 0
DefaultHeartbeatTTL = 5


# InstanceRegisterRequest 注册服务请求
class InstanceRegisterRequest:
    def __init__(self, service: str, service_token: str, namespace: str, host: str, port: int, protocol: str = '',
                 weight: int = 100, priority: int = 0, version: str = '', metadata: Dict[str, str] = None,
                 healthy: bool = True, ttl: int | None = None, timeout: int = 0, retry_count: int = 0,
                 auto_heartbeat: bool = False, instance_id: str = ''):
        # 服务名
        self.service = service
        # 服务访问Token
        self.service_token = service_token
        # 命名空间
        self.namespace = namespace
        # 服务实例ip
        self.host = host
        # 服务实例端口
        self.port = port

        # 以下字段可选，默认nil表示客户端不配置，使用服务端配置
        # 服务协议
        self.protocol = protocol
        # 服务权重，默认100，范围0-10000
        self.weight = weight
        # 实例优先级，默认为0，数值越小，优先级越高
        self.priority = priority
        # 实例提供服务版本号
        self.version = version
        # 用户自定义metadata信息
        if metadata is None:
            self.metadata = {}
        else:
            self.metadata = metadata
        # 该服务实例是否健康，默认健康
        self.healthy = healthy
        # ttl超时时间，单位：秒
        self.ttl = ttl
        self.auto_heartbeat = auto_heartbeat
        self.instance_id = instance_id

        # 可选，单次查询超时时间，默认直接获取全局的超时配置
        # 用户总最大超时时间为(1+RetryCount) * Timeout
        self.timeout = timeout
        # 可选，重试次数，默认直接获取全局的超时配置
        self.retry_count = retry_count

    def set_timeout(self, timeout: int):
        self.timeout = timeout

    def set_retry_count(self, retry_count: int):
        self.retry_count = retry_count

    # 验证request是否合理，返回SDKERROR
    def validate(self):
        if self.ttl is not None and (
            isinstance(self.ttl, bool) or not isinstance(self.ttl, int) or not 0 < self.ttl <= 0xFFFFFFFF
        ):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceRegisterRequest: heartbeat ttl must be a positive uint32 number of seconds")
        if not isinstance(self.auto_heartbeat, bool):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceRegisterRequest: auto_heartbeat must be a boolean")
        if len(self.service_token) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceRegisterRequest: serviceToken should not be empty")
        if len(self.service) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceRegisterRequest: serviceName should not be empty when instanceId is empty")
        if len(self.namespace) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceRegisterRequest: namespace should not be empty when instanceId is empty")
        if len(self.host) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceRegisterRequest: host should not be empty when instanceId is empty")
        if self.port <= 0 or self.port >= 65536:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceRegisterRequest: port should be in range (0, 65536)")
        if self.weight < MinWeight or self.weight > MaxWeight:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceRegisterRequest: weight should be in range [%d, %d]" % (MinWeight, MaxWeight))
        if self.priority < MinPriority or self.priority > MaxPriority:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceRegisterRequest: priority should be in range [%d, %d]" % (MinPriority, MaxPriority))


# 校验元数据的key是否为空
def validate_metadata(prefix: str, metadata: Dict[str, str]):
    for key in metadata:
        if len(key) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "validate_metadata: %s: metadata has empty key" % prefix)
    return True


# InstanceRegisterResponse 注册服务响应
class InstanceRegisterResponse:
    def __init__(self, instance_id):
        self.instance_id = instance_id


# InstanceDiscoverRequest 服务发现请求
class InstanceDiscoverRequest:
    def __init__(self, type, name, namespace, revision=""):
        self.type = type
        self.name = name
        self.namespace = namespace
        self.revision = revision


# ReportClientRequest 客户端上报请求信息
class ReportClientRequest:
    def __init__(self, version: str, host: str = "", timeout: int = 0, persist_handler=None,
                 client_id: str = "", reporter_meta_infos=None):
        self.client_id = client_id
        self.reporter_meta_infos = reporter_meta_infos or []
        # 客户端IP地址
        self.host = host
        # 客户端版本信息
        self.version = version
        # 可选，单次查询超时时间，默认直接获取全局的超时配置
        # 用户总最大超时时间为(1+RetryCount) * Timeout
        self.timeout = timeout
        # 持久化回调
        self.persist_handler = persist_handler

    def set_timeout(self, timeout: int):
        self.timeout = timeout

    def validate(self):
        if len(self.version) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ReportClientRequest: version should not be empty")


# ReportClientRequest 客户端上报响应信息
class ReportClientResponse:
    def __init__(self, region: str, zone: str, campus: str, mode: int = 0, version: str = ""):
        self.mode = mode
        self.version = version
        self.region = region
        self.zone = zone
        self.campus = campus


# 心跳上报请求
class InstanceHeartbeatRequest:
    def __init__(self, service: str, service_token: str, namespace: str, instance_id: str, host: str, port: int,
                 timeout: int = 0, retry_count: int = 0):
        # 必选，服务名
        self.service = service
        # 必选，服务访问Token
        self.service_token = service_token
        # 必选，命名空间
        self.namespace = namespace
        # 必选，服务实例ID
        self.instance_id = instance_id
        # 必选，服务实例ip
        self.host = host
        # 必选，服务实例端口
        self.port = port
        # 可选，单次查询超时时间，默认直接获取全局的超时配置
        # 用户总最大超时时间为(1+RetryCount) * Timeout
        self.timeout = timeout
        # 可选，重试次数，默认直接获取全局的超时配置
        self.retry_count = retry_count

    def set_timeout(self, duration: int):
        self.timeout = duration

    def set_retry_count(self, retry_count: int):
        self.retry_count = retry_count

    def validate(self):
        if len(self.service_token) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceHeartbeatRequest: serviceToken should not be empty")
        if len(self.instance_id) > 0:
            return
        if len(self.service) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceHeartbeatRequest: serviceName should not be empty when instanceId is empty")
        if len(self.namespace) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceHeartbeatRequest: namespace should not be empty when instanceId is empty")
        if len(self.host) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceHeartbeatRequest: host should not be empty when instanceId is empty")
        if self.port <= 0 or self.port >= 65536:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "InstanceHeartbeatRequest: port should be in range (0, 65536)")

# class ServiceStr:
#     def __init__(self, name, namespace):
#         self.name = name
#         self.namespace = namespace
#         self.metadata = None
#         self.ports = ''
#         self.business = ''
#         self.department = ''
#         self.cmdb_mod1 = ''
#         self.cmdb_mod2 = ''
#         self.cmd_mod3 = ''
#         self.comment = ''
#         self.owners = ''
#         self.token = ''
#         self.ctime = ''
#         self.mtime = ''
#         self.revision = ''
