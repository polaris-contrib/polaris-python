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

import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from polaris.api._log_file import (
    DEFAULT_BACKUP_COUNT, DEFAULT_MAX_AGE_DAYS, DEFAULT_MAX_BYTES,
    ExclusiveRotatingFileHandler, LogRetention, reserve_log_files,
)
from polaris.pkg.model.error import ErrorCode, SDKError

default_log_dir = "./polaris/log"
default_log_path = f"{default_log_dir}/base/polaris.log"
LOG_CATEGORIES = (
    "base", "stat", "statReport", "detect", "network", "cache", "event",
    "lossless", "route", "auth", "circuitbreaker",
)
default_logger: logging.Logger | None = None
_logger_lock = RLock()
_context_logger = ContextVar("polaris_context_logger", default=None)
_context_log_files = set()
_process_loggers = {}
_process_log_paths = {}
_process_file_locks = {}
_process_retention = None
_process_rotation = (DEFAULT_MAX_BYTES, DEFAULT_BACKUP_COUNT, DEFAULT_MAX_AGE_DAYS)


@dataclass
class LogOptions:
    """Assign log options in code; each context captures their values at creation."""

    level: str | None = None
    file_path: str | Path | None = None
    max_bytes: int = DEFAULT_MAX_BYTES
    backup_count: int = DEFAULT_BACKUP_COUNT
    log_dir: str | Path | None = None
    max_age_days: int = DEFAULT_MAX_AGE_DAYS


def _validate_category(category):
    if category not in LOG_CATEGORIES:
        raise ValueError(f"Unknown log category: {category}")


def _log_paths(file_path=None, log_dir=None, client_id=None):
    """Resolve every category now, so later environment changes cannot move logs."""
    if file_path is not None and log_dir is not None:
        raise ValueError("Specify either log_dir or file_path")
    if file_path is None and log_dir is None:
        configured_path = os.getenv("POLARIS_LOG_PATH")
        if configured_path:
            candidate = Path(configured_path).expanduser()
            if candidate.is_dir() or not candidate.suffix or configured_path.endswith(("/", "\\")):
                log_dir = candidate
            else:
                file_path = candidate
        else:
            log_dir = default_log_dir
    if log_dir is not None:
        root = Path(log_dir).expanduser().resolve()
        stem, suffix = "polaris", ".log"
        base = root / "base" / f"{stem}{suffix}"
    else:
        base = Path(file_path).expanduser().resolve()
        root = base.parent.parent if base.parent.name == "base" else base.parent
        stem, suffix = base.stem, base.suffix or ".log"
    identity = f"-{client_id}" if client_id is not None else ""
    paths = {
        category: (root / category / f"{stem}-{category}{identity}{suffix}").resolve()
        for category in LOG_CATEGORIES if category != "base"
    }
    paths["base"] = base.with_name(f"{stem}{identity}{suffix}") if identity else base
    return paths


def _create_file_logger(name, path, level, max_bytes, backup_count, max_age_days=DEFAULT_MAX_AGE_DAYS):
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = ExclusiveRotatingFileHandler(path, "a", max_bytes, backup_count,
                                          encoding="utf-8", max_age_days=max_age_days)
    handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s][%(process)d]: %(message)s"))
    instance = logging.Logger(name, level=level)
    instance.addHandler(handler)
    instance.propagate = False
    return instance, handler


class _ContextCategoryLogger(logging.LoggerAdapter):
    def __init__(self, instance, handler, client_id, path):
        super().__init__(instance, {"client_id": client_id})
        self.handler = handler
        self.file_path = path

    def process(self, msg, kwargs):
        """Prefix every entry with this context's stable client ID."""
        msg, kwargs = super().process(msg, kwargs)
        return f"[clientId={self.extra['client_id']}] {msg}", kwargs


class ContextLogger(_ContextCategoryLogger):
    """Own independent rotating category logs for one SDK context."""

    def __init__(self, client_id, options: LogOptions | None = None):
        options = options if options is not None else LogOptions()
        if not isinstance(options, LogOptions):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "Context log options must be LogOptions")
        level = options.level if options.level is not None else os.getenv("POLARIS_LOG_LEVEL", "info")
        if not isinstance(level, str):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "Context log level must be a string")
        level = level.lower()
        if level not in LogLevelMap:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"Invalid context log level: {level}")
        if (type(options.max_bytes) is not int or options.max_bytes <= 0
                or type(options.backup_count) is not int or options.backup_count < 0
                or type(options.max_age_days) is not int or options.max_age_days < 0):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "Invalid context log rotation options")
        if options.file_path is not None and not isinstance(options.file_path, (str, Path)):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "Context log file path must be a string or Path")
        if options.log_dir is not None and not isinstance(options.log_dir, (str, Path)):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "Context log directory must be a string or Path")
        try:
            self._paths = _log_paths(options.file_path, options.log_dir,
                                     client_id=None if options.file_path is not None else client_id)
        except (OSError, ValueError) as error:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, str(error)) from error
        self._level = LogLevelMap[level]
        self._max_bytes = options.max_bytes
        self._backup_count = options.backup_count
        self._max_age_days = options.max_age_days
        self._close_lock = RLock()
        self._closed = False
        self._owner_pid = os.getpid()
        self._categories = {}
        self._file_locks = {}
        self._retention = None
        with _logger_lock:
            collisions = set(self._paths.values()) & _context_log_files
            if collisions:
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig,
                               f"Context log file is already in use: {next(iter(collisions))}")
            try:
                self._file_locks = reserve_log_files(self._paths.values())
                instance, handler = _create_file_logger(
                    f"polaris.{client_id}.base", self._paths["base"], self._level,
                    self._max_bytes, self._backup_count, self._max_age_days,
                )
            except (OSError, ValueError) as error:
                for lock in self._file_locks.values():
                    lock.close()
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig,
                               f"Cannot open context log file: {self._paths['base']}") from error
            super().__init__(instance, handler, client_id, self._paths["base"])
            self._categories["base"] = self
            _context_log_files.update(self._paths.values())
        family_paths = ()
        if options.file_path is None:
            family_paths = [path.with_name(f"{path.stem[:-len(client_id) - 1]}{path.suffix}")
                            for path in self._paths.values()]
        self._retention = LogRetention(self._file_locks, self._max_age_days, self._backup_count, family_paths)
        self._retention.add_handler(handler)
        try:
            self._retention.start()
        except Exception:
            self.close()
            raise

    def get_logger(self, category="base"):
        """Open a category on first use, sharing this context's captured options."""
        _validate_category(category)
        if self._owner_pid != os.getpid():
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "Create an independent SDK context after fork")
        with self._close_lock:
            if self._closed:
                raise SDKError(ErrorCode.ErrCodeInvalidStateError, "Context logger has been closed")
            if category not in self._categories:
                path = self._paths[category]
                with self._retention.lock:
                    try:
                        instance, handler = _create_file_logger(
                            f"polaris.{self.extra['client_id']}.{category}", path, self._level,
                            self._max_bytes, self._backup_count, self._max_age_days,
                        )
                    except (OSError, ValueError) as error:
                        raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig,
                                       f"Cannot open context log file: {path}") from error
                    self._retention.add_handler(handler)
                self._categories[category] = _ContextCategoryLogger(instance, handler, self.extra['client_id'], path)
            return self._categories[category]

    def close(self):
        """Close all owned category handlers and release their paths."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            if self._retention is not None:
                self._retention.close()
            for instance in self._categories.values():
                instance.logger.removeHandler(instance.handler)
                instance.handler.close()
            with _logger_lock:
                for lock in self._file_locks.values():
                    lock.close()
                self._file_locks.clear()
                _context_log_files.difference_update(self._paths.values())


@contextmanager
def use_context_logger(instance):
    """Bind logging to a context for one thread or asynchronous task."""
    token = _context_logger.set(instance)
    try:
        yield
    finally:
        _context_logger.reset(token)


class LogLevel:
    Debug = "debug"
    Info = "info"
    Warn = "warn"
    Error = "error"


LogLevelMap = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARN,
    "error": logging.ERROR
}


def _get_log_level(level):
    return LogLevelMap.get(level, logging.INFO)


def init_log(level=None, file_path=None, *, log_dir=None, max_bytes=DEFAULT_MAX_BYTES,
             backup_count=DEFAULT_BACKUP_COUNT, max_age_days=DEFAULT_MAX_AGE_DAYS):
    """Initialize process logging; explicit options take precedence over POLARIS_LOG_* values."""
    global default_logger
    with _logger_lock:
        if default_logger is None:
            if level is None:
                level = os.getenv("POLARIS_LOG_LEVEL", LogLevel.Info).lower()
            if log_dir is None:
                if file_path is None:
                    file_path = _log_paths()["base"]
                default_logger = create_log(level, file_path, max_bytes, backup_count, max_age_days=max_age_days)
            else:
                default_logger = create_log(level, file_path, max_bytes, backup_count,
                                            log_dir=log_dir, max_age_days=max_age_days)
    return default_logger


def create_log(level=LogLevel.Info, file_path=None, max_bytes=DEFAULT_MAX_BYTES, backup_count=DEFAULT_BACKUP_COUNT,
               *, log_dir=None, max_age_days=DEFAULT_MAX_AGE_DAYS):
    """Create process logs; category files are opened on first use."""
    global default_logger, _process_rotation, _process_retention
    if (type(max_bytes) is not int or max_bytes <= 0
            or type(backup_count) is not int or backup_count < 0
            or type(max_age_days) is not int or max_age_days < 0):
        raise ValueError("Invalid process log rotation options")
    if file_path is None and log_dir is None:
        log_dir = default_log_dir
    paths = _log_paths(file_path, log_dir)
    with _logger_lock:
        retained = _process_file_locks if _process_retention is None or _process_retention.owner_pid == os.getpid() else {}
        locks = reserve_log_files(paths.values(), retained=retained)
        try:
            instance, handler = _create_file_logger("polaris", paths["base"], _get_log_level(level),
                                                    max_bytes, backup_count, max_age_days)
        except Exception:
            for path, lock in locks.items():
                if path not in retained:
                    lock.close()
            raise
        replaces_default = default_logger is not None and default_logger is _process_loggers.get("base")
        _close_process_logs(retained=locks)
        _process_file_locks.update(locks)
        _process_log_paths.update(paths)
        _process_rotation = (max_bytes, backup_count, max_age_days)
        _process_loggers["base"] = instance
        _process_retention = LogRetention(_process_file_locks, max_age_days, backup_count)
        _process_retention.add_handler(handler)
        try:
            _process_retention.start()
        except Exception:
            _close_process_logs()
            raise
        if replaces_default:
            default_logger = instance
        return instance


def _close_process_logs(retained=None):
    global _process_retention
    if _process_retention is not None:
        _process_retention.close()
        _process_retention = None
    for instance in _process_loggers.values():
        for handler in instance.handlers[:]:
            instance.removeHandler(handler)
            handler.close()
    _process_loggers.clear()
    _process_log_paths.clear()
    retained = retained or {}
    for path, lock in _process_file_locks.items():
        if path not in retained:
            lock.close()
    _process_file_locks.clear()


def set_logger(instance):
    """Set the process logger used outside context-bound SDK operations."""
    global default_logger
    with _logger_lock:
        if instance is not _process_loggers.get("base"):
            _close_process_logs()
        default_logger = instance


def _get_logger(category="base"):
    bound_logger = _context_logger.get()
    if bound_logger is not None:
        if isinstance(bound_logger, ContextLogger):
            return bound_logger.get_logger(category)
        return bound_logger
    global default_logger
    with _logger_lock:
        if default_logger is None:
            default_logger = logging.getLogger("polaris")
            default_logger.addHandler(logging.NullHandler())
        if category != "base" and default_logger is _process_loggers.get("base"):
            if _process_retention.owner_pid != os.getpid():
                raise SDKError(ErrorCode.ErrCodeInvalidStateError, "Reinitialize process logging after fork")
            if category not in _process_loggers:
                with _process_retention.lock:
                    instance, handler = _create_file_logger(
                        f"polaris.{category}", _process_log_paths[category], default_logger.level, *_process_rotation,
                    )
                    _process_retention.add_handler(handler)
                _process_loggers[category] = instance
            return _process_loggers[category]
        return default_logger


class CategoryLogger:
    """Resolve the current context at emission time, including across async tasks."""

    def __init__(self, category):
        _validate_category(category)
        self.category = category

    def debug(self, msg, *args, **kwargs):
        _emit(self.category, "debug", msg, args, kwargs)

    def info(self, msg, *args, **kwargs):
        _emit(self.category, "info", msg, args, kwargs)

    def warning(self, msg, *args, **kwargs):
        _emit(self.category, "warning", msg, args, kwargs)

    def error(self, msg, *args, **kwargs):
        _emit(self.category, "error", msg, args, kwargs)

    def __getattr__(self, name):
        return getattr(_get_logger(self.category), name)


def get_logger(category="base"):
    """Get a context-aware logger for a polaris-go category such as network or cache."""
    return CategoryLogger(category)


def _emit(category, method, msg, args, kwargs):
    try:
        getattr(_get_logger(category), method)(msg, *args, **kwargs)
    except Exception as err:  # pylint: disable=broad-except
        logging.getLogger("polaris").error("log err! msg: %s; args: %s; err: %s", msg, json.dumps(args), repr(err))


def debug(msg, *args, **kwargs):
    _emit("base", "debug", msg, args, kwargs)


def info(msg, *args, **kwargs):
    _emit("base", "info", msg, args, kwargs)


def warning(msg, *args, **kwargs):
    _emit("base", "warning", msg, args, kwargs)


def error(msg, *args, **kwargs):
    _emit("base", "error", msg, args, kwargs)
