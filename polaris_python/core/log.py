"""SDK loggers, kept separate from the application's logging setup.

Layout follows polaris-go ``pkg/log``: one logger per concern, each rolling
file under ``./polaris/log/<channel>/``. Handlers never propagate, so SDK
records do not reach the application's handlers or format.

``base/polaris.log``
    Context lifecycle, register and deregister, discovery errors, degradation.
``network/polaris-network.log``
    gRPC reconnect and retry.
``cache/polaris-cache.log``
    Snapshot changes and local cache read or write failures.
``circuitbreaker/polaris-circuitbreaker.log``
    Circuit state transitions.
``heartbeat/polaris-instance-heartbeat.log``
    Heartbeat results. polaris-go records these on the base logger; this file
    matches polaris-java so the heartbeat stream does not fill ``polaris.log``.

``Config.log_dir`` empty disables the files and still drops SDK records.
Logging is process-wide: the most recently created ``SDKContext`` decides it.
"""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polaris_python.core.config import Config

DEFAULT_LOG_DIR = "./polaris/log"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 5

BASE_LOGGER = "polaris_python"
NETWORK_LOGGER = "polaris_python.network"
CACHE_LOGGER = "polaris_python.cache"
CIRCUIT_BREAKER_LOGGER = "polaris_python.circuitbreaker"
HEARTBEAT_LOGGER = "polaris_python.heartbeat"

ROOT_LOGGER = BASE_LOGGER
UPDATE_EVENT_LOGGER = CACHE_LOGGER

LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)s [%(process)d:%(threadName)s:%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_CHANNELS = {
    BASE_LOGGER: ("base", "polaris.log"),
    NETWORK_LOGGER: ("network", "polaris-network.log"),
    CACHE_LOGGER: ("cache", "polaris-cache.log"),
    CIRCUIT_BREAKER_LOGGER: ("circuitbreaker", "polaris-circuitbreaker.log"),
    HEARTBEAT_LOGGER: ("heartbeat", "polaris-instance-heartbeat.log"),
}

_lock = threading.Lock()
_installed: list[tuple[logging.Logger, logging.Handler]] = []
_applied: tuple[object, ...] | None = None


def configure_logging(config: Config) -> None:
    """Apply ``config`` to the SDK loggers.

    Safe to call repeatedly: handlers from an earlier call are replaced. When
    the log directory cannot be created, SDK records are discarded and a
    message is written to stderr.
    """
    global _applied
    log_dir = config.resolved_log_dir
    settings = (str(log_dir) if log_dir else "", config.log_level, config.log_max_bytes, config.log_backup_count)
    with _lock:
        if settings == _applied:
            return
        _remove_handlers()
        error: OSError | None = None
        if log_dir is None:
            _install_null_handlers()
        else:
            try:
                _install_files(config, log_dir)
            except OSError as exc:
                _remove_handlers()
                _install_null_handlers()
                error = exc
        logging.getLogger(BASE_LOGGER).setLevel(config.log_level)
        _applied = settings
    if error is not None:
        print(f"polaris: cannot write SDK logs to {log_dir}: {error}", file=sys.stderr)


def _install_files(config: Config, log_dir: Path) -> None:
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    for name, (directory, filename) in _CHANNELS.items():
        path = (log_dir / directory / filename).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=config.log_max_bytes,
            backupCount=config.log_backup_count,
            encoding="utf-8",
            delay=True,
        )
        handler.setFormatter(formatter)
        _attach(logging.getLogger(name), handler)


def _install_null_handlers() -> None:
    for name in _CHANNELS:
        _attach(logging.getLogger(name), logging.NullHandler())


def _attach(logger: logging.Logger, handler: logging.Handler) -> None:
    logger.addHandler(handler)
    logger.propagate = False
    _installed.append((logger, handler))


def _remove_handlers() -> None:
    for logger, handler in _installed:
        logger.removeHandler(handler)
        handler.close()
        logger.propagate = True
    _installed.clear()


def _reset_logging() -> None:
    """Drop SDK handlers so a later ``configure_logging`` starts clean."""
    global _applied
    with _lock:
        _remove_handlers()
        logging.getLogger(BASE_LOGGER).setLevel(logging.NOTSET)
        _applied = None
