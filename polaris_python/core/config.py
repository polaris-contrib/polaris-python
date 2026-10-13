"""Configuration objects used by the SDK runtime."""

from __future__ import annotations

import json
import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from polaris_python.core.log import (
    DEFAULT_LOG_BACKUP_COUNT,
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_MAX_BYTES,
)

DEFAULT_PERSIST_DIR = "./polaris/backup"
_FLOAT_FIELDS = {
    "timeout_seconds",
    "retry_backoff_seconds",
    "refresh_interval_seconds",
    "persist_retry_interval_seconds",
    "service_expire_seconds",
    "min_register_interval_seconds",
}
_INT_FIELDS = {
    "retry_attempts",
    "persist_max_write_retry",
    "persist_max_read_retry",
    "log_max_bytes",
    "log_backup_count",
}
_BOOL_FIELDS = {"zero_protection", "service_expire_enable", "report_enable"}


@dataclass
class Config:
    """SDK configuration.

    Server address, namespace, timeout, access token, retry, discovery refresh,
    local persistence, cache expiry, degradation, registration and logging
    settings. Defaults follow polaris-java.

    Each discovered resource is backed up under ``persist_dir`` (default
    ``./polaris/backup``) for restart recovery; an empty ``persist_dir`` keeps
    the cache in memory only. With ``service_expire_enable`` a service nobody
    has read for ``service_expire_seconds`` stops refreshing and is removed
    from memory and disk.

    ``min_register_interval_seconds`` is how long after the first registration
    a lost instance may be registered again by the heartbeat task.

    ``report_enable`` reports this client to Polaris every 60 seconds through
    ``ReportClient``. The reported address is ``bind_ip``, or the local
    address used to reach the first server, or ``127.0.0.1``.

    Logs go to ``log_dir`` (default ``./polaris/log``) and do not propagate to
    the application's loggers. An empty ``log_dir`` discards SDK logs.
    ``log_level`` defaults to ``INFO``. ``token`` is excluded from ``repr``.

    Values can be built in code, loaded from JSON/TOML, or loaded from the
    ``POLARIS_`` environment variables. Explicit values always win over
    environment and file values when callers compose configuration themselves.
    """

    server_addresses: list[str] = field(default_factory=list)
    namespace: str = ""
    timeout_seconds: float = 1.0
    token: str = field(default="", repr=False)
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.1
    refresh_interval_seconds: float = 2.0
    persist_dir: str | None = DEFAULT_PERSIST_DIR
    persist_max_write_retry: int = 1
    persist_max_read_retry: int = 0
    persist_retry_interval_seconds: float = 0.5
    service_expire_enable: bool = False
    service_expire_seconds: float = 24 * 60 * 60
    zero_protection: bool = False
    min_register_interval_seconds: float = 30.0
    report_enable: bool = True
    bind_ip: str = ""
    log_dir: str | None = DEFAULT_LOG_DIR
    log_level: str | None = DEFAULT_LOG_LEVEL
    log_max_bytes: int = DEFAULT_LOG_MAX_BYTES
    log_backup_count: int = DEFAULT_LOG_BACKUP_COUNT

    def __post_init__(self) -> None:
        """Normalize and validate values supplied by callers."""
        self.server_addresses = [address.strip() for address in self.server_addresses if address.strip()]
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if self.retry_attempts < 0:
            raise ValueError("retry_attempts must not be negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")
        if self.refresh_interval_seconds <= 0:
            raise ValueError("refresh_interval_seconds must be greater than zero")
        if self.persist_dir is None:
            self.persist_dir = DEFAULT_PERSIST_DIR
        if self.persist_max_write_retry < 0 or self.persist_max_read_retry < 0:
            raise ValueError("persist_max_write_retry and persist_max_read_retry must not be negative")
        if self.persist_retry_interval_seconds < 0:
            raise ValueError("persist_retry_interval_seconds must not be negative")
        if self.service_expire_seconds <= 0:
            raise ValueError("service_expire_seconds must be greater than zero")
        if self.min_register_interval_seconds < 0:
            raise ValueError("min_register_interval_seconds must not be negative")
        if self.log_dir is None:
            self.log_dir = DEFAULT_LOG_DIR
        if not self.log_level:
            self.log_level = DEFAULT_LOG_LEVEL
        self.log_level = self.log_level.upper()
        if not isinstance(logging.getLevelName(self.log_level), int):
            raise ValueError(f"log_level must be a logging level name, got {self.log_level!r}")
        if self.log_max_bytes < 0 or self.log_backup_count < 0:
            raise ValueError("log_max_bytes and log_backup_count must not be negative")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> Config:
        """Create configuration from a mapping using SDK field names."""
        aliases = {
            "server_address": "server_addresses",
            "server": "server_addresses",
            "timeout": "timeout_seconds",
        }
        normalized: dict[str, Any] = {}
        for key, value in values.items():
            normalized[aliases.get(key, key)] = value
        addresses = normalized.get("server_addresses", [])
        if isinstance(addresses, str):
            addresses = [item for item in addresses.split(",") if item.strip()]
        normalized["server_addresses"] = list(addresses)
        supported = {field_name for field_name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in normalized.items() if key in supported})

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> Config:
        """Load configuration from a JSON or TOML file."""
        config_path = Path(path)
        with config_path.open("rb") as stream:
            values = tomllib.load(stream) if config_path.suffix.lower() == ".toml" else json.load(stream)
        return cls.from_mapping(values)

    @classmethod
    def from_env(cls, prefix: str = "POLARIS_") -> Config:
        """Load configuration from environment variables."""
        values: dict[str, Any] = {}
        environment_names = {
            "SERVER_ADDRESSES": "server_addresses",
            "NAMESPACE": "namespace",
            "TIMEOUT_SECONDS": "timeout_seconds",
            "TOKEN": "token",
            "RETRY_ATTEMPTS": "retry_attempts",
            "RETRY_BACKOFF_SECONDS": "retry_backoff_seconds",
            "REFRESH_INTERVAL_SECONDS": "refresh_interval_seconds",
            "PERSIST_DIR": "persist_dir",
            "PERSIST_MAX_WRITE_RETRY": "persist_max_write_retry",
            "PERSIST_MAX_READ_RETRY": "persist_max_read_retry",
            "PERSIST_RETRY_INTERVAL_SECONDS": "persist_retry_interval_seconds",
            "SERVICE_EXPIRE_ENABLE": "service_expire_enable",
            "SERVICE_EXPIRE_SECONDS": "service_expire_seconds",
            "ZERO_PROTECTION": "zero_protection",
            "MIN_REGISTER_INTERVAL_SECONDS": "min_register_interval_seconds",
            "REPORT_ENABLE": "report_enable",
            "BIND_IP": "bind_ip",
            "LOG_DIR": "log_dir",
            "LOG_LEVEL": "log_level",
            "LOG_MAX_BYTES": "log_max_bytes",
            "LOG_BACKUP_COUNT": "log_backup_count",
        }
        for suffix, field_name in environment_names.items():
            value = os.getenv(f"{prefix}{suffix}")
            if value is None:
                continue
            if field_name in _FLOAT_FIELDS:
                value = float(value)
            elif field_name in _INT_FIELDS:
                value = int(value)
            elif field_name in _BOOL_FIELDS:
                value = value.strip().lower() in {"1", "true", "yes", "on"}
            elif field_name == "server_addresses":
                value = [item.strip() for item in value.split(",") if item.strip()]
            values[field_name] = value
        return cls.from_mapping(values)

    @property
    def resolved_persist_dir(self) -> Path | None:
        """Return the expanded backup directory, or None when disk persistence is off."""
        return Path(self.persist_dir).expanduser() if self.persist_dir else None

    @property
    def resolved_log_dir(self) -> Path | None:
        """Return the expanded log directory, or None when file logging is off."""
        return Path(self.log_dir).expanduser() if self.log_dir else None
