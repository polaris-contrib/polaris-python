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

"""Load Configuration objects from YAML and environment variables."""

from __future__ import annotations

import copy
import inspect
import os
import re
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from polaris.pkg.config.stat_reporter import AdminConfig, PrometheusConfig
from polaris.pkg.config.event import PushGatewayEventConfig

from polaris.pkg.config.api import (
    AIConfig,
    SkillConfig,
    SkillConnectorConfig,
    APIConfig,
    CircuitBreakerConfig,
    Configuration,
    ConsumerConfig,
    GlobalConfig,
    LoadBalancerConfig,
    LocalCacheConfig,
    ProviderConfig,
    ServerClusterConfig,
    ServerConnectorConfig,
    ServiceRouterConfig,
    StatReporterConfig,
    SystemConfig,
    EventReporterConfig,
)
from polaris.pkg.model.error import ErrorCode, SDKError

DEFAULT_CONFIG_FILE_NAMES = ("polaris.yaml",)
ENV_CONFIG_FILE = "POLARIS_CONFIG_FILE"

_CAMEL_CASE = re.compile(r"(?<!^)(?=[A-Z])")
_ENV_VARIABLE = re.compile(
    r"\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<default>[^}]*))?\}"
    r"|\$(?P<bare>[A-Za-z_][A-Za-z0-9_]*)"
)
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ns|us|ms|s|m|h)")
_DURATION_UNITS = {
    "ns": Decimal("0.000001"), "us": Decimal("0.001"), "ms": Decimal(1),
    "s": Decimal(1000), "m": Decimal(60000), "h": Decimal(3600000),
}

_FIELD_ALIASES = {
    Configuration: {"global": "global_config", "consumer": "consumer_config", "provider": "provider_config"},
    GlobalConfig: {
        "system": "system_conf",
        "api": "api_conf",
        "server_connector": "server_connector",
        "serverconnector": "server_connector",
        "stat_reporter": "stat_reporter",
        "statreporter": "stat_reporter",
        "event_reporter": "event_reporter",
        "eventreporter": "event_reporter",
    },
    ConsumerConfig: {
        "load_balance": "load_balance",
        "loadbalancer": "load_balance",
        "load_balancer": "load_balance",
    },
    APIConfig: {"bind_i_p": "bind_ip", "bind_if": "bind_intf"},
    ServerConnectorConfig: {"message_timeout": "message_time", "trusted_c_a_file": "trusted_ca_file"},
    SkillConnectorConfig: {"trusted_c_a_file": "trusted_ca_file"},
}

_NESTED_TYPES = {
    Configuration: {
        "global_config": GlobalConfig,
        "consumer_config": ConsumerConfig,
        "provider_config": ProviderConfig,
        "ai": AIConfig,
    },
    GlobalConfig: {
        "system_conf": SystemConfig,
        "api_conf": APIConfig,
        "server_connector": ServerConnectorConfig,
        "stat_reporter": StatReporterConfig,
        "admin": AdminConfig,
        "event_reporter": EventReporterConfig,
    },
    SystemConfig: {
        "discover_cluster": ServerClusterConfig,
        "health_check_cluster": ServerClusterConfig,
        "monitor_cluster": ServerClusterConfig,
    },
    ConsumerConfig: {
        "local_cache": LocalCacheConfig,
        "service_router": ServiceRouterConfig,
        "load_balance": LoadBalancerConfig,
        "circuit_breaker": CircuitBreakerConfig,
    },
    AIConfig: {"skill": SkillConfig},
    SkillConfig: {"server_connector": SkillConnectorConfig},
}

_DURATION_FIELDS = {
    PrometheusConfig: {"push_interval"},
    PushGatewayEventConfig: {"push_interval", "retry_interval"},
    ProviderConfig: {"min_register_interval"},
    ServerClusterConfig: {"refresh_interval"},
    APIConfig: {"timeout", "report_interval", "retry_interval"},
    ServerConnectorConfig: {
        "connect_timeout", "message_time", "connection_idle_timeout", "server_switch_interval",
    },
    LocalCacheConfig: {"service_expire_time", "service_refresh_interval", "persist_retry_interval"},
    CircuitBreakerConfig: {"check_period", "sleep_window", "default_interval"},
    SkillConnectorConfig: {"message_timeout", "download_timeout", "persist_retry_interval"},
}


def _snake_case(name: str) -> str:
    return _CAMEL_CASE.sub("_", name.replace("-", "_")).lower()


def _normalise_keys(cls: type, data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise SDKError(
            ErrorCode.ErrCodeAPIInvalidConfig,
            f"Configuration section for {cls.__name__} must be an object",
        )

    aliases = _FIELD_ALIASES.get(cls, {})
    result: dict[str, Any] = {}
    for key, value in data.items():
        normalised = _snake_case(str(key))
        field = aliases.get(normalised, normalised)
        if field in aliases and aliases[field] != field:
            field = aliases[field]
        result[field] = value
    return result


def _normalise_sections(cls: type, data: Mapping[str, Any]) -> dict[str, Any]:
    values = _normalise_keys(cls, data)
    for key, nested_type in _NESTED_TYPES.get(cls, {}).items():
        if isinstance(values.get(key), Mapping):
            values[key] = _normalise_sections(nested_type, values[key])
    return values


def _duration_ms(value: Any, path: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"[+-]?\d+", text):
            return int(text)
        sign = -1 if text.startswith("-") else 1
        remaining = text[1:] if text.startswith(("+", "-")) else text
        total = Decimal(0)
        matched = False
        try:
            while remaining:
                match = _DURATION_PART.match(remaining)
                if match is None:
                    break
                matched = True
                total += Decimal(match[1]) * _DURATION_UNITS[match[2]]
                remaining = remaining[match.end():]
            if matched and not remaining and total == total.to_integral_value():
                return sign * int(total)
        except InvalidOperation:
            pass
    raise SDKError(
        ErrorCode.ErrCodeAPIInvalidConfig,
        f"{path} must be integer milliseconds or a duration such as 1000ms or 1s",
    )


def _expand_environment(value: Any, env: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            braced = match.group("braced")
            if braced is not None:
                replacement = env.get(braced)
                if replacement:
                    return replacement
                return match.group("default") or ""
            return env.get(match.group("bare"), "")

        return _ENV_VARIABLE.sub(replace, value)
    if isinstance(value, Mapping):
        return {key: _expand_environment(child, env) for key, child in value.items()}
    if isinstance(value, list):
        return [_expand_environment(child, env) for child in value]
    return value


def _build_object(cls: type, data: Mapping[str, Any], path: str) -> Any:
    values = _normalise_keys(cls, data)
    signature = inspect.signature(cls.__init__).parameters
    accepted = set(signature) - {"self"}
    unknown = sorted(set(values) - accepted)
    if unknown:
        raise SDKError(
            ErrorCode.ErrCodeAPIInvalidConfig,
            f"Unknown configuration keys at {path}: {', '.join(unknown)}",
        )

    nested_types = _NESTED_TYPES.get(cls, {})
    kwargs: dict[str, Any] = {}
    for key, value in values.items():
        nested_type = nested_types.get(key)
        if nested_type is not None:
            kwargs[key] = None if value is None else _build_object(nested_type, value, f"{path}.{key}")
        elif key in _DURATION_FIELDS.get(cls, set()):
            kwargs[key] = _duration_ms(value, f"{path}.{key}")
        else:
            kwargs[key] = value

    try:
        return cls(**kwargs)
    except TypeError as exc:
        raise SDKError(
            ErrorCode.ErrCodeAPIInvalidConfig,
            f"Invalid configuration at {path}: {exc}",
        ) from exc


def parse_config_stream(buf: str | bytes, source: str = "config stream") -> dict[str, Any]:
    """Parse a YAML configuration document."""
    try:
        text = buf.decode("utf-8") if isinstance(buf, bytes) else buf
        if not isinstance(text, str):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"{source} must be YAML text or bytes")
        data = yaml.safe_load(text)
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise SDKError(
            ErrorCode.ErrCodeAPIInvalidConfig,
            f"Failed to parse {source}: {exc}",
        ) from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"{source} must contain a configuration object")
    return data


def load_config_file(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser()
    if not config_path.is_file():
        raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"Configuration file not found: {config_path}")
    if config_path.suffix.lower() != ".yaml":
        raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "Only .yaml configuration files are supported")
    try:
        return parse_config_stream(config_path.read_bytes(), str(config_path))
    except OSError as exc:
        raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"Failed to read configuration file: {config_path}") from exc


def _set_nested(data: dict[str, Any], keys: tuple[str, ...], value: Any) -> None:
    target = data
    for key in keys[:-1]:
        child = target.get(key)
        if not isinstance(child, dict):
            child = {}
            target[key] = child
        target = child
    target[keys[-1]] = value


def _as_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"Invalid boolean environment value: {value}")


def _as_int(value: str, name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"{name} must be an integer") from exc


def _as_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def apply_environment(data: Mapping[str, Any] | None = None,
                      environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Overlay POLARIS_ environment variables on a configuration mapping."""
    # Merge overrides into the same section regardless of its key spelling.
    result = _normalise_sections(Configuration, copy.deepcopy(dict(data or {})))
    env = os.environ if environ is None else environ
    global_config = result.get("global_config")
    connector = global_config.get("server_connector", {}) if isinstance(global_config, Mapping) else {}
    addresses = connector.get("addresses", []) if isinstance(connector, Mapping) else []
    server_is_placeholder = isinstance(addresses, list) and any(
        isinstance(address, str) and any(
            (match.group("braced") or match.group("bare")) == "POLARIS_SERVER"
            for match in _ENV_VARIABLE.finditer(address)
        )
        for address in addresses
    )
    result = _expand_environment(result, env)

    def value(name: str) -> str | None:
        return env.get(name)

    server_address = value("POLARIS_SERVER_ADDRESSES") or value("POLARIS_SERVER_ADDRESS")
    if not server_address and not server_is_placeholder:
        server_address = value("POLARIS_SERVER")
    if server_address:
        _set_nested(result, ("global_config", "server_connector", "addresses"), _as_list(server_address))
    if (token := value("POLARIS_TOKEN")) is not None:
        _set_nested(result, ("global_config", "server_connector", "token"), token)
    if protocol := value("POLARIS_PROTOCOL"):
        _set_nested(result, ("global_config", "server_connector", "protocol"), protocol)

    timeout = value("POLARIS_API_TIMEOUT") or value("POLARIS_TIMEOUT")
    if timeout:
        _set_nested(result, ("global_config", "api_conf", "timeout"), _as_int(timeout, "POLARIS_TIMEOUT"))
    retries = value("POLARIS_API_MAX_RETRY_TIMES") or value("POLARIS_MAX_RETRY_TIMES")
    if retries:
        _set_nested(result, ("global_config", "api_conf", "max_retry_times"), _as_int(retries, "POLARIS_MAX_RETRY_TIMES"))
    retry_interval = value("POLARIS_API_RETRY_INTERVAL") or value("POLARIS_RETRY_INTERVAL")
    if retry_interval:
        _set_nested(result, ("global_config", "api_conf", "retry_interval"),
                    _as_int(retry_interval, "POLARIS_RETRY_INTERVAL"))

    persist_dir = value("POLARIS_LOCAL_CACHE_PERSIST_DIR") or value("POLARIS_CACHE_PERSIST_DIR")
    if persist_dir:
        _set_nested(result, ("consumer_config", "local_cache", "persist_dir"), persist_dir)
    refresh_interval = value("POLARIS_SERVICE_REFRESH_INTERVAL")
    if refresh_interval:
        _set_nested(result, ("consumer_config", "local_cache", "service_refresh_interval"),
                    _as_int(refresh_interval, "POLARIS_SERVICE_REFRESH_INTERVAL"))
    expire_time = value("POLARIS_SERVICE_EXPIRE_TIME")
    if expire_time:
        _set_nested(result, ("consumer_config", "local_cache", "service_expire_time"),
                    _as_int(expire_time, "POLARIS_SERVICE_EXPIRE_TIME"))

    stat_enable = value("POLARIS_STAT_REPORTER_ENABLE")
    if stat_enable:
        _set_nested(result, ("global_config", "stat_reporter", "enable"), _as_bool(stat_enable))
    stat_chain = value("POLARIS_STAT_REPORTER_CHAIN")
    if stat_chain:
        _set_nested(result, ("global_config", "stat_reporter", "chain"), _as_list(stat_chain))
    return result


def build_configuration(data: Mapping[str, Any], apply_env: bool = True,
                        environ: Mapping[str, str] | None = None) -> Configuration:
    values = apply_environment(data, environ) if apply_env else dict(data)
    return _build_object(Configuration, values, "configuration")


def find_default_config_file(environ: Mapping[str, str] | None = None) -> Path | None:
    env = os.environ if environ is None else environ
    if configured := env.get(ENV_CONFIG_FILE):
        return Path(configured).expanduser()

    candidates = [Path.cwd() / name for name in DEFAULT_CONFIG_FILE_NAMES]
    candidates.extend(Path.home() / ".config" / "polaris" / name for name in DEFAULT_CONFIG_FILE_NAMES)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None
