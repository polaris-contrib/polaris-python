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
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Lossless online/offline models aligned with the Java LosslessPolicy plugin."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class RegisterStatus(Enum):
    """Whether a lossless instance has completed its registration."""

    UNREGISTERED = "UNREGISTERED"
    REGISTERED = "REGISTERED"


@dataclass(frozen=True)
class LosslessInstance:
    """Identify one provider instance participating in lossless lifecycle."""

    namespace: str
    service: str
    host: str
    port: int
    metadata: Dict[str, str] = field(default_factory=dict)

    def __hash__(self):
        return hash((self.namespace, self.service, self.host, self.port))

    def __eq__(self, other):
        if not isinstance(other, LosslessInstance):
            return NotImplemented
        return (self.namespace, self.service, self.host, self.port) == (
            other.namespace, other.service, other.host, other.port)

    @classmethod
    def from_register_request(cls, request) -> "LosslessInstance":
        return cls(
            namespace=request.namespace,
            service=request.service,
            host=request.host,
            port=request.port,
            metadata=dict(getattr(request, "metadata", {}) or {}),
        )


class InstanceProperties:
    """Properties a lossless policy may set on the instance before registration."""

    def __init__(self) -> None:
        self._properties: Dict[str, Any] = {}

    def set_property(self, key: str, value: Any) -> None:
        self._properties[key] = value

    def get_property(self, key: str) -> Any:
        return self._properties.get(key)

    @property
    def properties(self) -> Dict[str, Any]:
        return dict(self._properties)


class LosslessActionProvider(ABC):
    """Callbacks that perform the real register, deregister and health checks."""

    @abstractmethod
    def get_name(self) -> str:
        """Return the provider name used in logs."""

    @abstractmethod
    async def do_register(self, instance_properties: InstanceProperties):
        """Register the instance after the lossless-online gate."""

    @abstractmethod
    async def do_deregister(self):
        """Deregister the instance when lossless offline is triggered."""

    @abstractmethod
    def is_enable_health_check(self) -> bool:
        """Return True to register after a successful health check."""

    @abstractmethod
    async def do_health_check(self) -> bool:
        """Return True when the instance is ready to receive traffic."""
