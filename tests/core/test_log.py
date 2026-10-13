from __future__ import annotations

import logging
from pathlib import Path

import pytest

from polaris_python.core.config import Config
from polaris_python.core.log import (
    BASE_LOGGER,
    CACHE_LOGGER,
    CIRCUIT_BREAKER_LOGGER,
    HEARTBEAT_LOGGER,
    NETWORK_LOGGER,
    configure_logging,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_channels_write_separate_files_and_skip_the_application(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    configure_logging(Config(log_dir=str(tmp_path)))

    with caplog.at_level(logging.DEBUG):
        logging.getLogger("polaris_python.api.context").info("main-line")
        logging.getLogger(CACHE_LOGGER).info("cache-line")
        logging.getLogger(NETWORK_LOGGER).warning("network-line")
        logging.getLogger(CIRCUIT_BREAKER_LOGGER).info("circuit-line")
        logging.getLogger(HEARTBEAT_LOGGER).info("heartbeat-line")

    assert caplog.records == []
    base = _read(tmp_path / "base" / "polaris.log")
    cache = _read(tmp_path / "cache" / "polaris-cache.log")
    network = _read(tmp_path / "network" / "polaris-network.log")
    circuit = _read(tmp_path / "circuitbreaker" / "polaris-circuitbreaker.log")
    heartbeat = _read(tmp_path / "heartbeat" / "polaris-instance-heartbeat.log")
    assert "main-line" in base
    assert "cache-line" not in base and "network-line" not in base
    assert "cache-line" in cache and "main-line" not in cache
    assert "network-line" in network
    assert "circuit-line" in circuit
    assert "heartbeat-line" in heartbeat


def test_reconfigure_replaces_sdk_handlers(tmp_path: Path) -> None:
    configure_logging(Config(log_dir=str(tmp_path / "a")))
    configure_logging(Config(log_dir=str(tmp_path / "b")))

    handlers = logging.getLogger(BASE_LOGGER).handlers
    assert len(handlers) == 1
    assert Path(handlers[0].baseFilename) == (tmp_path / "b" / "base" / "polaris.log").resolve()


def test_log_level_filters_the_base_file(tmp_path: Path) -> None:
    configure_logging(Config(log_dir=str(tmp_path), log_level="warning"))

    logging.getLogger("polaris_python.api.context").info("hidden")
    logging.getLogger("polaris_python.api.context").warning("visible")

    text = _read(tmp_path / "base" / "polaris.log")
    assert "visible" in text and "hidden" not in text


def test_empty_log_dir_discards_records(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging(Config(log_dir=""))

    with caplog.at_level(logging.DEBUG):
        logging.getLogger("polaris_python.api.context").error("discarded")

    root = logging.getLogger(BASE_LOGGER)
    assert caplog.records == []
    assert root.propagate is False
    assert root.handlers and all(isinstance(handler, logging.NullHandler) for handler in root.handlers)


def test_unusable_log_dir_discards_records_and_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")

    configure_logging(Config(log_dir=str(blocker)))

    assert "cannot write SDK logs" in capsys.readouterr().err
    root = logging.getLogger(BASE_LOGGER)
    assert root.propagate is False
    assert all(isinstance(handler, logging.NullHandler) for handler in root.handlers)
