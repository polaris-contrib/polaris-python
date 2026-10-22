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

"""Public configuration shared with the Java Prometheus reporter."""

from dataclasses import dataclass, field
import re
from urllib.parse import urlsplit

from polaris.pkg.model.error import ErrorCode, SDKError

DEFAULT_ADMIN_PORT = 28080


class AdminConfig:
    """Assign the SDK metrics HTTP listener address."""

    def __init__(self, host=None, port=None):
        self.host = host
        self.port = port

    def set_default(self):
        if self.host is None:
            self.host = "0.0.0.0"
        if self.port is None:
            self.port = DEFAULT_ADMIN_PORT

    def verify(self):
        if not isinstance(self.host, str) or not self.host.strip():
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "global.admin.host must be nonempty")
        if type(self.port) is not int or not -1 <= self.port <= 65535:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "global.admin.port must be -1..65535")


@dataclass
class PrometheusConfig:
    """Assign pull or push export and Java-compatible method aggregation."""

    type: str = "pull"
    path: str = "/metric"
    address: list[str] = field(default_factory=list)
    namespace: str = "Polaris"
    service: str = "polaris.pushgateway"
    push_interval: int = 10000
    open_gzip: bool = False
    path_regex_list: list[str] = field(default_factory=list)
    override_host: str = ""

    def verify(self):
        if self.type not in ("pull", "push"):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "prometheus.type must be pull or push")
        if not isinstance(self.path, str) or not self.path.startswith("/") or "?" in self.path:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "prometheus.path must be an absolute HTTP path")
        if type(self.push_interval) is not int or self.push_interval < 1000:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "prometheus.pushInterval must be >= 1000ms")
        if type(self.open_gzip) is not bool:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "prometheus.openGzip must be boolean")
        for key in ("address", "path_regex_list"):
            value = getattr(self, key)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"prometheus.{key} must be a list of strings")
        for key in ("namespace", "service", "override_host"):
            if not isinstance(getattr(self, key), str):
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"prometheus.{key} must be a string")
        for address in self.address:
            try:
                url = urlsplit(address if "://" in address else f"http://{address}")
                if (url.scheme not in ("http", "https") or not url.hostname or not url.port
                        or url.username or url.password or url.query or url.fragment):
                    raise ValueError("require http(s) host:port without credentials, query or fragment")
            except ValueError as error:
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"Invalid prometheus.address: {error}") from error
        if self.type == "push" and not self.address and (not self.namespace or not self.service):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "prometheus push requires address or namespace/service")
        try:
            for pattern in self.path_regex_list:
                re.compile(pattern)
        except re.error as error:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"Invalid prometheus pathRegexList: {error}") from error


def prometheus_config(value):
    """Parse YAML plugin mappings or capture directly assigned configuration objects."""
    if isinstance(value, PrometheusConfig):
        result = value
    else:
        from polaris.pkg.config.loader import _build_object
        result = _build_object(PrometheusConfig, value or {}, "global.statReporter.plugin.prometheus")
    result.verify()
    return result
