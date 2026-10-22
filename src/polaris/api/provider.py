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

from polaris.pkg.model.server import (
    InstanceDeRegisterRequest,
    InstanceHeartbeatRequest,
    InstanceRegisterRequest,
    InstanceRegisterResponse,
)
from polaris.pkg.config.api import Configuration
from polaris.pkg.model.error import SDKError, ErrorCode
from polaris.api.config import SDKContext, init_context_by_config, init_context_by_file
from polaris.api.log import LogOptions


class ProviderAPI:
    """Register instances and manage their heartbeats through a shared SDK context."""

    def __init__(self, context: SDKContext):
        self.context = context

    def check_available(self):
        if not self.context:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "providerAPI can not be None")
        if self.context.is_destroy():
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "providerAPI: api instance has been destroyed")

    def register(self, request: InstanceRegisterRequest) -> InstanceRegisterResponse:
        """Register synchronously, using the request's automatic-heartbeat setting."""
        self.check_available()
        request.validate()
        return self.context.get_engine().sync_register(request)

    def register_instance(self, request: InstanceRegisterRequest) -> InstanceRegisterResponse:
        """Register synchronously and let the SDK maintain instance heartbeats."""
        self.check_available()
        request.validate()
        request.auto_heartbeat = True
        return self.context.get_engine().sync_register(request)

    def deregister(self, request: InstanceDeRegisterRequest) -> None:
        """Stop automatic heartbeats and synchronously deregister the instance."""
        self.check_available()
        request.validate()
        return self.context.get_engine().sync_deregister(request)

    def heartbeat(self, request: InstanceHeartbeatRequest) -> None:
        """Synchronously send one explicit instance heartbeat."""
        self.check_available()
        request.validate()
        return self.context.get_engine().sync_heartbeat(request)

    def deregister_instance(self, request: InstanceDeRegisterRequest) -> None:
        """Stop automatic heartbeats and synchronously deregister an instance."""
        return self.deregister(request)

    async def async_register(self, request: InstanceRegisterRequest) -> InstanceRegisterResponse:
        """Asynchronously register with the request's automatic-heartbeat setting."""
        self.check_available()
        request.validate()
        return await self.context.get_engine().async_register(request)

    async def async_register_instance(self, request: InstanceRegisterRequest) -> InstanceRegisterResponse:
        """Asynchronously register and let the SDK maintain instance heartbeats."""
        self.check_available()
        request.validate()
        request.auto_heartbeat = True
        return await self.context.get_engine().async_register(request)

    async def async_deregister(self, request: InstanceDeRegisterRequest) -> None:
        """Stop automatic heartbeats and asynchronously deregister the instance."""
        self.check_available()
        request.validate()
        return await self.context.get_engine().async_deregister(request)

    async def async_heartbeat(self, request: InstanceHeartbeatRequest) -> None:
        """Asynchronously send one explicit instance heartbeat."""
        self.check_available()
        request.validate()
        return await self.context.get_engine().async_heartbeat(request)

    async def async_deregister_instance(self, request: InstanceDeRegisterRequest) -> None:
        """Stop automatic heartbeats and asynchronously deregister an instance."""
        return await self.async_deregister(request)

    def report_service_contract(self, request):
        """Synchronously report tools, resources, prompts and handler descriptors."""
        self.check_available()
        request.validate()
        return self.context.get_engine().sync_contract_call("report_service_contract", request)

    async def async_report_service_contract(self, request):
        """Asynchronously report a service contract."""
        self.check_available()
        request.validate()
        return await self.context.get_engine().async_contract_call("report_service_contract", request)

    def destroy(self) -> None:
        """Destroy the shared context and stop all of its heartbeat tasks."""
        if self.context:
            self.context.destroy()


def create_provider_by_file(path: str, *, log_options: LogOptions | None = None) -> ProviderAPI:
    context = init_context_by_file(path=path, log_options=log_options)
    return ProviderAPI(context=context)


def create_provider_by_config(config: Configuration, *, log_options: LogOptions | None = None) -> ProviderAPI:
    context = init_context_by_config(config=config, log_options=log_options)
    return ProviderAPI(context=context)


def create_provider_by_default_config_file(*, log_options: LogOptions | None = None) -> ProviderAPI:
    from polaris.api.config import init_context
    return ProviderAPI(context=init_context(log_options=log_options))
