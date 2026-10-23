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

"""Public configuration for the Java/Go-compatible event reporter."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from polaris.pkg.model.error import ErrorCode, SDKError


@dataclass
class PushGatewayEventConfig:
    """Configure batching and addressing for the event Pushgateway reporter."""

    address: list[str] = field(default_factory=list)
    event_queue_size: int = 1000
    max_batch_size: int = 100
    namespace: str = "Polaris"
    service: str = "polaris.pushgateway"
    report_path: str = "/polaris/client/events"
    push_interval: int = 1000
    max_retries: int = 3
    retry_interval: int = 1000
    override_host: str = ""

    def verify(self):
        for key in ("address",):
            value = getattr(self, key)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"pushgateway.{key} must be a list of strings")
        for key in ("event_queue_size", "max_batch_size", "push_interval", "max_retries"):
            value = getattr(self, key)
            if type(value) is not int or value <= 0:
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"pushgateway.{key} must be positive")
        if type(self.retry_interval) is not int or self.retry_interval < 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "pushgateway.retryInterval must be >=0")
        for key in ("namespace", "service", "report_path"):
            if not isinstance(getattr(self, key), str) or not getattr(self, key).strip():
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"pushgateway.{key} must be nonempty")
        if not isinstance(self.override_host, str):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "pushgateway.overrideHost must be a string")
        if not self.report_path.startswith("/") or "?" in self.report_path or "#" in self.report_path:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "pushgateway.reportPath must be an absolute path")
        for address in self.address:
            try:
                url = urlsplit(address if "://" in address else f"http://{address}")
                if (url.scheme not in ("http", "https") or not url.hostname or not url.port
                        or url.username or url.password or url.query or url.fragment):
                    raise ValueError("require http(s) host:port without credentials, query or fragment")
            except ValueError as error:
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"Invalid pushgateway.address: {error}") from error


def pushgateway_event_config(value):
    """Parse YAML plugin mappings or capture directly assigned configuration objects."""
    if isinstance(value, PushGatewayEventConfig):
        result = value
    else:
        from polaris.pkg.config.loader import _build_object
        result = _build_object(PushGatewayEventConfig, value or {}, "global.eventReporter.plugin.pushgateway")
    result.verify()
    return result
