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

from polaris.pkg.model.core import EventType
from polarismesh_specification.api.v1.service_manage import response_pb2
from polaris.pkg.model.error import SDKError, ErrorCode

from abc import ABCMeta, abstractmethod


# ServiceRule 服务配置通用接口
class ServiceRule(metaclass=ABCMeta):
    @abstractmethod
    def get_type(self):
        pass

    @abstractmethod
    def get_value(self):
        pass

    @abstractmethod
    def is_initialized(self):
        pass

    @abstractmethod
    def get_revision(self):
        pass


# 通用的服务规则实现
class SimpleServiceRule(ServiceRule):
    def __init(self, event_type: EventType, value, initialized: bool, revision: str):
        self.event_type = event_type
        self.value = value
        self.initialized = initialized
        self.revision = revision

    def get_type(self):
        return self.event_type

    def get_value(self):
        return self.value

    def is_initialized(self):
        return self.initialized

    def get_revision(self):
        return self.revision


# 创建通用的服务规则
def new_simple_service_rule(event_type: EventType, value, revision: str) -> ServiceRule:
    svc_rule = SimpleServiceRule()
    svc_rule.event_type = event_type
    if value is None:
        svc_rule.initialized = False
        return svc_rule
    svc_rule.initialized = True
    svc_rule.value = value
    svc_rule.revision = revision
    return svc_rule


# 获取服务规则请求
class GetServiceRuleRequest:
    def __init__(self, flow_id: int = 0, namespace: str = "", service: str = "", timeout: int = 0,
                 retry_count: int = 0):
        # 可选，流水号，用于跟踪用户的请求，默认0
        self.flow_id = flow_id
        # 命名空间
        self.namespace = namespace
        # 服务名
        self.service = service
        # 可选，仅对同步请求有效，本次查询最大超时信息，可选，默认直接获取全局的超时配置
        self.timeout = timeout
        # 可选，重试次数，默认直接获取全局的超时配置
        self.retry_count = retry_count

    def get_service(self):
        return self.service

    def get_namespace(self):
        return self.namespace

    def get_metadata(self):
        return None

    def set_timeout(self, duration: int):
        self.timeout = duration

    def set_retry_count(self, retry_count: int):
        self.retry_count = retry_count

    def validate(self):
        validate_service_metadata(self)


# 服务规则应答
class ServiceRuleResponse(ServiceRule):
    def __init__(self, event_type: EventType, value, revision: str):
        self.event_type = event_type
        self.value = value
        self.revision = revision

    def get_type(self):
        return self.event_type

    def get_value(self):
        return self.value

    def is_initialized(self):
        return True

    def get_revision(self):
        return self.revision


class RoutingRuleInProto:
    @classmethod
    def new_from_discover_rsp(cls, resp: response_pb2.DiscoverResponse) -> ServiceRule:
        if resp is None:
            return new_simple_service_rule(event_type=EventType.Routing, value=None, revision="")
        elif resp.routing is None:
            return new_simple_service_rule(event_type=EventType.Routing, value=None, revision="")
        else:
            return new_simple_service_rule(event_type=EventType.Routing, value=resp.routing,
                                           revision=str(resp.routing.revision.value))


def validate_service_metadata(svc_meta):
    if len(svc_meta.get_service()) == 0:
        raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "validate_service_metadata: service is empty")
    if len(svc_meta.get_namespace()) == 0:
        raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "validate_service_metadata: namespace is empty")
    metadata = svc_meta.get_metadata()
    if metadata is not None and len(metadata) > 0:
        for k, v in svc_meta.get_metadata():
            if len(k) == 0 or len(v) == 0:
                raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                               "validate_service_metadata: metadata has empty key or value")
