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

"""Framework-independent service contract models."""

from dataclasses import dataclass, field
from enum import IntEnum

from polarismesh_specification.api.v1.service_manage import contract_pb2

from polaris.pkg.model.error import ErrorCode, SDKError


class ServiceFeatureType(IntEnum):
    """Capability categories defined by the service contract protocol."""

    MCP_TOOL = contract_pb2.Service_Feature_Type_MCP_Tool
    MCP_RESOURCE = contract_pb2.Service_Feature_Type_MCP_Resource
    MCP_PROMPT = contract_pb2.Service_Feature_Type_MCP_Prompt


class ServiceFeatureStatus(IntEnum):
    """Availability of a published service capability."""

    ENABLED = contract_pb2.Service_Feature_Status_Enabled
    DISABLED = contract_pb2.Service_Feature_Status_Disabled


@dataclass
class ServiceFeature:
    """One tool, resource or prompt in a service contract."""

    type: int
    name: str
    description: str = ""
    content: str = ""
    status: int = ServiceFeatureStatus.ENABLED


@dataclass
class InterfaceDescriptor:
    """One request or notification handler exposed by a service."""

    name: str = ""
    method: str = ""
    path: str = ""
    content: str = ""


@dataclass
class GetServiceContractRequest:
    """Identify a service contract by namespace, service, protocol and version."""

    namespace: str
    service: str
    protocol: str = ""
    version: str = ""
    timeout: int = 0

    def validate(self):
        """Check the service identity and timeout."""
        if not self.namespace.strip() or not self.service.strip() or self.timeout < 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "contract namespace/service are required, timeout >=0")


@dataclass
class ServiceContract(GetServiceContractRequest):
    """A service contract used for reporting and retrieval."""

    name: str = ""
    revision: str = ""
    content: str = ""
    service_features: list[ServiceFeature] = field(default_factory=list)
    interfaces: list[InterfaceDescriptor] = field(default_factory=list)


ReportServiceContractRequest = ServiceContract
