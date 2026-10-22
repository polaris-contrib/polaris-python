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

from polaris.pkg.model.service import ServiceCallResult
from polaris.pkg.model.rule import GetServiceRuleRequest, ServiceRuleResponse
from polaris.pkg.model.server import (
    InstanceDeRegisterRequest,
    InstanceHeartbeatRequest,
    InstanceRegisterRequest,
    InstanceRegisterResponse,
)


class BaseEngine(object):
    def destroy(self):
        pass

    def sync_get_one_instance(self, request):
        pass

    def sync_get_instances(self, request):
        pass

    def sync_register(self, request: InstanceRegisterRequest) -> InstanceRegisterResponse:
        pass

    def sync_deregister(self, request: InstanceDeRegisterRequest) -> None:
        pass

    async def async_register(self, request: InstanceRegisterRequest) -> InstanceRegisterResponse:
        pass

    async def async_deregister(self, request: InstanceDeRegisterRequest) -> None:
        pass

    async def async_get_one_instance(self, request):
        pass

    async def async_get_instances(self):
        pass

    def sync_heartbeat(self, request: InstanceHeartbeatRequest) -> None:
        pass

    async def async_heartbeat(self, request: InstanceHeartbeatRequest) -> None:
        pass

    def sync_update_service_call_result(self, req: ServiceCallResult):
        pass

    def sync_get_service_rule(self, event_type: int, req: GetServiceRuleRequest) -> ServiceRuleResponse:
        pass

