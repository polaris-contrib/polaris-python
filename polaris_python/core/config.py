"""Configuration objects used by the SDK runtime."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass
class Config:
    """SDK configuration.

    Server address, namespace, timeout, access token, retry and cache settings.

    Values can be built in code, loaded from JSON/TOML, or loaded from the
    ``POLARIS_`` environment variables. Explicit values always win over
    environment and file values when callers compose configuration themselves.
    """

    server_addresses: list[str] = field(default_factory=list)
    namespace: str = ""
    timeout_seconds: float = 1.0
    token: str = ""
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.1
    cache_file: str | None = None
    log_level: str = "WARNING"

    def __post_init__(self) -> None:
        """Normalize and validate values supplied by callers."""
        self.server_addresses = [address.strip() for address in self.server_addresses if address.strip()]
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if self.retry_attempts < 0:
            raise ValueError("retry_attempts must not be negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> Config:
        """Create configuration from a mapping using SDK field names."""
        aliases = {
            "server_address": "server_addresses",
            "server": "server_addresses",
            "timeout": "timeout_seconds",
            "cache": "cache_file",
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
            "CACHE_FILE": "cache_file",
            "LOG_LEVEL": "log_level",
        }
        for suffix, field_name in environment_names.items():
            value = os.getenv(f"{prefix}{suffix}")
            if value is None:
                continue
            if field_name in {"timeout_seconds", "retry_backoff_seconds"}:
                value = float(value)
            elif field_name == "retry_attempts":
                value = int(value)
            elif field_name == "server_addresses":
                value = [item.strip() for item in value.split(",") if item.strip()]
            values[field_name] = value
        return cls.from_mapping(values)

    @property
    def resolved_cache_file(self) -> Path | None:
        """Return the expanded cache path, if disk persistence is enabled."""
        return Path(self.cache_file).expanduser() if self.cache_file else None
