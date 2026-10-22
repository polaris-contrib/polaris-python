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

from polaris.pkg.config.api import Configuration
from polaris.pkg.model.service import (GetInstancesRequest, GetOneInstanceRequest, InstancesResponse,
                                      ServiceCallResult, Instance)
from polaris.pkg.model.rule import ServiceRuleResponse, GetServiceRuleRequest
from polaris.api.config import SDKContext, init_context_by_config, init_context_by_file
from polaris.api.log import LogOptions
from polaris.pkg.model.error import SDKError, ErrorCode
from polaris.pkg.flow.async_flow import CacheResult
from polaris.pkg.model.core import EventType


class ConsumerAPI:
    def __init__(self, context: SDKContext):
        self.context = context

    def check_available(self):
        if not self.context:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "consumeAPI can not be None")
        if self.context.is_destroy():
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "consumeAPI: api instance has been destroyed")

    def get_one_instance(self, request: GetOneInstanceRequest) -> Instance:
        self.check_available()
        request.validate()

        return self.context.get_engine().sync_get_one_instance(request)

    def get_instances(self, request: GetInstancesRequest) -> InstancesResponse:
        """Return locally filtered candidates without selecting or consuming a half-open permit."""
        self.check_available()
        request.validate()

        return self.context.get_engine().sync_get_instances(request)

    def get_all_instances(self, request: GetInstancesRequest) -> InstancesResponse:
        """Return every cached instance, including isolated and unhealthy nodes."""
        self.check_available()
        request.validate()
        return self.context.get_engine().sync_get_all_instances(request)

    def get_healthy_instances(self, request: GetInstancesRequest) -> InstancesResponse:
        """Return candidates using only isolation and recovery filters."""
        self.check_available()
        request.validate()
        return self.context.get_engine().sync_get_healthy_instances(request)

    def sync_update_service_call_result(self, request: ServiceCallResult):
        self.check_available()
        request.validate()

        return self.context.get_engine().sync_update_service_call_result(request)

    async def async_get_one_instance(self, request: GetOneInstanceRequest) -> Instance:
        self.check_available()
        request.validate()

        return await self.context.get_engine().async_get_one_instance(req=request)

    async def async_get_instances(self, request: GetInstancesRequest) -> InstancesResponse:
        self.check_available()
        request.validate()

        return await self.context.get_engine().async_get_instances(req=request)

    async def async_get_all_instances(self, request: GetInstancesRequest) -> InstancesResponse:
        """Asynchronously return the full snapshot."""
        self.check_available()
        request.validate()
        return await self.context.get_engine().async_get_all_instances(request)

    async def async_get_healthy_instances(self, request: GetInstancesRequest) -> InstancesResponse:
        """Asynchronously return isolation and recovery candidates."""
        self.check_available()
        request.validate()
        return await self.context.get_engine().async_get_healthy_instances(request)

    async def get_route_rule(self, request: GetServiceRuleRequest) -> ServiceRuleResponse:
        """Routing rules are not cached and this call raises SDKError."""
        self.check_available()
        request.validate()

        return await self.context.get_engine().sync_get_service_rule(event_type=EventType.Routing, req=request)

    def update_service_call_result(self, request: ServiceCallResult):
        """Synchronously report invocation metrics and the existing local instance result."""
        return self.sync_update_service_call_result(request)

    async def async_update_service_call_result(self, request: ServiceCallResult):
        """Asynchronously report invocation metrics on this context's owner loop."""
        self.check_available()
        request.validate()

        return await self.context.get_engine().async_update_service_call_result(request)

    def get_service_contract(self, request):
        """Synchronously fetch a contract from the registry."""
        self.check_available()
        request.validate()
        return self.context.get_engine().sync_contract_call("get_service_contract", request)

    async def async_get_service_contract(self, request):
        """Asynchronously fetch a contract from the registry."""
        self.check_available()
        request.validate()
        return await self.context.get_engine().async_contract_call("get_service_contract", request)

    def destroy(self):
        if self.context:
            self.context.destroy()


def create_consumer_by_file(path: str, *, log_options: LogOptions | None = None) -> ConsumerAPI:
    context = init_context_by_file(path, log_options=log_options)
    return ConsumerAPI(context)


def create_consumer_by_config(config: Configuration, *, log_options: LogOptions | None = None) -> ConsumerAPI:
    context = init_context_by_config(config, log_options=log_options)
    return ConsumerAPI(context)


def create_consumer_by_default_config_file(*, log_options: LogOptions | None = None) -> ConsumerAPI:
    from polaris.api.config import init_context
    return ConsumerAPI(context=init_context(log_options=log_options))
