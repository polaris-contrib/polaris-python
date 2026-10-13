from __future__ import annotations

from pathlib import Path

import pytest

from polaris_python.core.config import Config


def test_config_reads_refresh_interval_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLARIS_REFRESH_INTERVAL_SECONDS", "0.5")

    assert Config.from_env().refresh_interval_seconds == 0.5


def test_config_rejects_non_positive_refresh_interval() -> None:
    with pytest.raises(ValueError, match="refresh_interval_seconds"):
        Config(refresh_interval_seconds=0)


def test_config_defaults_log_directory_like_polaris_go() -> None:
    config = Config()

    assert config.log_dir == "./polaris/log"
    assert config.resolved_log_dir == Path("./polaris/log")
    assert config.log_level == "INFO"
    assert config.log_max_bytes == 50 * 1024 * 1024
    assert config.log_backup_count == 5


def test_config_backs_up_to_polaris_backup_and_keeps_expiry_off_like_java() -> None:
    config = Config()

    assert config.resolved_persist_dir == Path("./polaris/backup")
    assert config.persist_max_write_retry == 1 and config.persist_retry_interval_seconds == 0.5
    assert not config.service_expire_enable
    assert config.service_expire_seconds == 24 * 60 * 60


def test_empty_persist_dir_turns_disk_backup_off() -> None:
    assert Config(persist_dir="").resolved_persist_dir is None


def test_config_reads_cache_expiry_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLARIS_SERVICE_EXPIRE_ENABLE", "true")
    monkeypatch.setenv("POLARIS_SERVICE_EXPIRE_SECONDS", "600")
    monkeypatch.setenv("POLARIS_PERSIST_MAX_WRITE_RETRY", "3")

    config = Config.from_env()

    assert config.service_expire_enable
    assert config.service_expire_seconds == 600
    assert config.persist_max_write_retry == 3


def test_config_reports_client_by_default_like_java(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Config().report_enable
    monkeypatch.setenv("POLARIS_REPORT_ENABLE", "false")
    monkeypatch.setenv("POLARIS_BIND_IP", "10.0.0.8")

    config = Config.from_env()

    assert not config.report_enable
    assert config.bind_ip == "10.0.0.8"


def test_config_rejects_non_positive_expire_time() -> None:
    with pytest.raises(ValueError, match="service_expire_seconds"):
        Config(service_expire_seconds=0)


def test_config_rejects_unknown_log_level() -> None:
    with pytest.raises(ValueError, match="log_level"):
        Config(log_level="verbose")


def test_config_reads_log_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLARIS_LOG_DIR", "/tmp/polaris-logs")
    monkeypatch.setenv("POLARIS_LOG_MAX_BYTES", "1024")

    config = Config.from_env()

    assert config.log_dir == "/tmp/polaris-logs"
    assert config.log_max_bytes == 1024


def test_config_repr_hides_token() -> None:
    assert "secret" not in repr(Config(token="secret"))
