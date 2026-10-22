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

from polarismesh_specification.api.v1.service_manage import response_pb2

from polaris.pkg.model.server import (
    InstanceDeRegisterRequest,
    InstanceDiscoverRequest,
    InstanceHeartbeatRequest,
    InstanceRegisterRequest,
    InstanceRegisterResponse,
    ReportClientRequest,
    ReportClientResponse,
)
from polaris.pkg.model.service import GetOneInstanceRequest, InstancesResponse

__all__ = ["BaseServerConnector"]


class BaseServerConnector(ABC):
    """
    同步注册服务
    """

    @abstractmethod
    async def register_instance(self, request: InstanceRegisterRequest) -> InstanceRegisterResponse:
        pass

    """
    同步反注册
    """

    @abstractmethod
    async def deregister_instance(self, request: InstanceDeRegisterRequest):
        pass

    """
    服务发现
    """

    @abstractmethod
    async def discover(
        self,
        request: InstanceDiscoverRequest,
        use_discover_cache: bool = True,
    ) -> response_pb2.DiscoverResponse:
        pass

    @abstractmethod
    async def stop_discover(self, request: InstanceDiscoverRequest) -> None:
        """Release discovery state for one resource after its reader has stopped."""
        pass

    """
    心跳上报
    """

    @abstractmethod
    async def heartbeat(self, request: InstanceHeartbeatRequest):
        pass

    """
    上报客户端
    """

    @abstractmethod
    async def report_client(self, request: ReportClientRequest) -> ReportClientResponse:
        pass

    """
    单次服务发现
    """
    @abstractmethod
    def get_one_instance(self, request: GetOneInstanceRequest) -> InstancesResponse:
        pass

    @abstractmethod
    async def close(self) -> None:
        """Release connector resources."""
        pass

    async def report_service_contract(self, request):
        """Report a contract when the connector supports the specification RPC."""
        from polaris.pkg.model.error import ErrorCode, SDKError
        raise SDKError(ErrorCode.ErrCodePluginError, "service contract reporting is unsupported by this connector")

    async def get_service_contract(self, request):
        """Retrieve a contract when the connector supports the specification RPC."""
        from polaris.pkg.model.error import ErrorCode, SDKError
        raise SDKError(ErrorCode.ErrCodePluginError, "service contract retrieval is unsupported by this connector")
