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

import asyncio
import logging
import multiprocessing
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest

from polaris.api import log
from polaris.pkg.config.api import Configuration
from polaris.pkg.model.error import SDKError


@pytest.fixture
def logging_options(monkeypatch, process_logs):
    calls = []
    logger = logging.Logger("polaris-test")

    def create_log(level, file_path, *args, **kwargs):
        calls.append((level, file_path))
        return logger

    monkeypatch.setattr(log, "default_logger", None)
    monkeypatch.setattr(log, "create_log", create_log)
    return calls, logger


def test_log_initialization_reads_independent_environment(monkeypatch, logging_options):
    calls, logger = logging_options
    monkeypatch.setenv("POLARIS_LOG_LEVEL", "ERROR")
    monkeypatch.setenv("POLARIS_LOG_PATH", "./independent.log")
    config = Configuration.from_env()
    config.set_default()
    assert calls == []
    assert log.init_log() is logger
    assert calls == [("error", Path("./independent.log").resolve())]


def test_explicit_logging_options_take_precedence_over_environment(monkeypatch, logging_options):
    calls, logger = logging_options
    monkeypatch.setenv("POLARIS_LOG_LEVEL", "ERROR")
    monkeypatch.setenv("POLARIS_LOG_PATH", "./env.log")
    assert log.init_log(level=log.LogLevel.Warn, file_path="./code.log") is logger
    assert calls == [("warn", "./code.log")]


def test_logging_initialization_uses_default_options(monkeypatch, logging_options):
    calls, logger = logging_options
    monkeypatch.delenv("POLARIS_LOG_LEVEL", raising=False)
    monkeypatch.delenv("POLARIS_LOG_PATH", raising=False)
    assert log.init_log() is logger
    assert calls == [("info", Path("./polaris/log/base/polaris.log").resolve())]


def test_logging_initialization_preserves_application_logger(monkeypatch, logging_options):
    calls, logger = logging_options
    monkeypatch.setenv("POLARIS_LOG_LEVEL", "ERROR")
    log.set_logger(logger)
    assert log.init_log() is logger
    assert calls == []


def test_context_logging_captures_environment_per_creation(monkeypatch, tmp_path):
    monkeypatch.setenv("POLARIS_LOG_PATH", str(tmp_path / "polaris.log"))
    monkeypatch.setenv("POLARIS_LOG_LEVEL", "DEBUG")
    first = log.ContextLogger("first")
    monkeypatch.setenv("POLARIS_LOG_LEVEL", "ERROR")
    second = log.ContextLogger("second")
    try:
        assert first.file_path == tmp_path / "polaris-first.log"
        assert second.file_path == tmp_path / "polaris-second.log"
        assert first.logger.level == logging.DEBUG
        assert second.logger.level == logging.ERROR
        first.debug("only-first")
        second.debug("hidden")
        second.error("only-second")
    finally:
        first.close()
        second.close()
    assert "[clientId=first] only-first" in first.file_path.read_text()
    assert "hidden" not in second.file_path.read_text()
    assert "[clientId=second] only-second" in second.file_path.read_text()


def test_context_log_file_can_be_reused_only_after_owner_closes(tmp_path):
    options = log.LogOptions(level="warn", file_path=tmp_path / "explicit.log")
    first = log.ContextLogger("first", options)
    try:
        with pytest.raises(SDKError, match="already in use"):
            log.ContextLogger("second", options)
    finally:
        first.close()
        first.close()
    second = log.ContextLogger("second", options)
    try:
        assert second.file_path == options.file_path
        assert second.logger.level == logging.WARNING
        second.warning("replacement")
    finally:
        second.close()
    assert "[clientId=second] replacement" in options.file_path.read_text()


@pytest.mark.parametrize("options", [
    log.LogOptions(level=""), log.LogOptions(level="invalid"), log.LogOptions(level=1),
    log.LogOptions(max_bytes=0), log.LogOptions(max_bytes=True),
    log.LogOptions(backup_count=-1), log.LogOptions(backup_count=1.5), log.LogOptions(file_path=1),
    log.LogOptions(log_dir=1), log.LogOptions(file_path="explicit.log", log_dir="logs"),
])
def test_invalid_context_log_options_create_no_files(options, tmp_path, monkeypatch):
    monkeypatch.setenv("POLARIS_LOG_PATH", str(tmp_path / "logs" / "polaris.log"))
    with pytest.raises(SDKError):
        log.ContextLogger("invalid", options)
    assert not (tmp_path / "logs").exists()


def test_failed_context_log_file_open_does_not_reserve_path(tmp_path):
    options = log.LogOptions(file_path=tmp_path)
    with pytest.raises(SDKError, match="Cannot open context log file"):
        log.ContextLogger("invalid", options)
    assert tmp_path not in log._context_log_files


def test_log_options_support_direct_code_assignment(monkeypatch, tmp_path):
    monkeypatch.setenv("POLARIS_LOG_LEVEL", "ERROR")
    monkeypatch.setenv("POLARIS_LOG_PATH", str(tmp_path / "environment.log"))
    options = log.LogOptions()
    options.level = "debug"
    options.file_path = tmp_path / "assigned.log"
    options.max_bytes = 4096
    options.backup_count = 2
    logger = log.ContextLogger("assigned", options)
    try:
        assert logger.logger.level == logging.DEBUG
        assert logger.file_path == options.file_path
        assert logger.handler.maxBytes == 4096
        assert logger.handler.backupCount == 2
        logger.debug("code-assigned")
    finally:
        logger.close()
    assert "code-assigned" in options.file_path.read_text()
    assert not (tmp_path / "environment.log").exists()


@pytest.mark.parametrize("category", log.LOG_CATEGORIES)
def test_default_context_logs_use_category_subdirectories(category, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("POLARIS_LOG_PATH", raising=False)
    monkeypatch.delenv("POLARIS_LOG_LEVEL", raising=False)
    context = log.ContextLogger("client")
    try:
        category_logger = context.get_logger(category)
        filename = "polaris-client.log" if category == "base" else f"polaris-{category}-client.log"
        assert category_logger.file_path == tmp_path / "polaris" / "log" / category / filename
        with log.use_context_logger(context):
            log.get_logger(category).info("message-%s", category)
        assert f"[clientId=client] message-{category}" in category_logger.file_path.read_text()
        if category != "base":
            assert f"message-{category}" not in context.file_path.read_text()
    finally:
        context.close()
    assert category_logger.handler.stream is None


@pytest.mark.parametrize("configured_path", ["logs", "logs/", "logs.v1/"])
def test_environment_log_directory_creates_category_files(configured_path, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POLARIS_LOG_PATH", configured_path)
    context = log.ContextLogger("client")
    try:
        assert context.file_path == tmp_path / configured_path / "base" / "polaris-client.log"
        assert context.get_logger("network").file_path == (
            tmp_path / configured_path / "network" / "polaris-network-client.log")
    finally:
        context.close()


def test_explicit_log_directory_captures_options_for_lazy_categories(tmp_path, monkeypatch):
    options = log.LogOptions(level="debug", log_dir=tmp_path / "assigned", max_bytes=4096, backup_count=2)
    monkeypatch.setenv("POLARIS_LOG_PATH", str(tmp_path / "environment.log"))
    context = log.ContextLogger("client", options)
    try:
        options.log_dir = tmp_path / "changed"
        options.level, options.max_bytes, options.backup_count = "error", 8192, 3
        monkeypatch.setenv("POLARIS_LOG_PATH", str(tmp_path / "changed-environment.log"))
        network = context.get_logger("network")
        assert network.file_path == tmp_path / "assigned" / "network" / "polaris-network-client.log"
        assert network.logger.level == logging.DEBUG
        assert network.handler.maxBytes == 4096
        assert network.handler.backupCount == 2
        assert not (tmp_path / "changed").exists()
        assert not (tmp_path / "environment.log").exists()
    finally:
        context.close()


def test_context_categories_rotate_independently_and_close_together(tmp_path):
    context = log.ContextLogger("client", log.LogOptions(log_dir=tmp_path, max_bytes=200, backup_count=1))
    network = context.get_logger("network")
    context.info("base entry")
    for index in range(4):
        network.info("network entry %s %s", index, "x" * 60)
    context.close()
    context.close()
    assert network.file_path.with_suffix(".log.1").exists()
    assert not context.file_path.with_suffix(".log.1").exists()
    assert "network entry" not in context.file_path.read_text()
    assert all(instance.handler.stream is None for instance in context._categories.values())
    assert not set(context._paths.values()) & log._context_log_files
    with pytest.raises(SDKError, match="closed"):
        context.get_logger("cache")


def test_context_reserves_category_paths_before_lazy_open(tmp_path):
    first = log.ContextLogger("first", log.LogOptions(file_path=tmp_path / "client.log"))
    path = tmp_path / "network" / "client-network.log"
    try:
        assert not path.exists()
        with pytest.raises(SDKError, match="already in use"):
            log.ContextLogger("second", log.LogOptions(file_path=path))
    finally:
        first.close()
    second = log.ContextLogger("second", log.LogOptions(file_path=path))
    second.close()


def test_failed_lazy_category_open_can_retry_and_releases_paths(tmp_path):
    context = log.ContextLogger("client", log.LogOptions(log_dir=tmp_path))
    blocker = context._paths["network"]
    blocker.mkdir()
    try:
        with pytest.raises(SDKError, match="Cannot open context log file"):
            context.get_logger("network")
        blocker.rmdir()
        context.get_logger("network").info("retry succeeded")
    finally:
        context.close()
    assert not set(context._paths.values()) & log._context_log_files


@pytest.mark.asyncio
async def test_shared_category_logger_routes_concurrent_tasks_to_their_context(tmp_path):
    network = log.get_logger("network")
    first = log.ContextLogger("first", log.LogOptions(level="debug", log_dir=tmp_path))
    second = log.ContextLogger("second", log.LogOptions(level="error", log_dir=tmp_path))

    async def emit(context):
        with log.use_context_logger(context):
            await asyncio.sleep(0)
            network.debug("private-debug-%s", context.extra["client_id"])
            network.error("private-error-%s", context.extra["client_id"])

    try:
        await asyncio.gather(emit(first), emit(second))
        one, two = first.get_logger("network"), second.get_logger("network")
        assert "private-debug-first" in one.file_path.read_text()
        assert "second" not in one.file_path.read_text()
        assert "private-debug" not in two.file_path.read_text()
        assert "private-error-second" in two.file_path.read_text()
        assert "first" not in two.file_path.read_text()
        first.close()
        await emit(second)
        assert one.handler.stream is None
        assert two.handler.stream is not None
        assert two.file_path.read_text().count("private-error-second") == 2
    finally:
        first.close()
        second.close()


@pytest.fixture
def process_logs(monkeypatch):
    monkeypatch.setattr(log, "default_logger", None)
    monkeypatch.setattr(log, "_process_loggers", {})
    monkeypatch.setattr(log, "_process_log_paths", {})
    monkeypatch.setattr(log, "_process_rotation", (50 * 1024 * 1024, 5, 30))
    try:
        yield
    finally:
        log._close_process_logs()


@pytest.mark.parametrize("source", ["default", "environment", "code", "file"])
def test_process_log_initialization_separates_categories(source, tmp_path, monkeypatch, process_logs):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("POLARIS_LOG_PATH", raising=False)
    monkeypatch.delenv("POLARIS_LOG_LEVEL", raising=False)
    root = tmp_path / "polaris" / "log"
    if source == "environment":
        root = tmp_path / "environment"
        monkeypatch.setenv("POLARIS_LOG_PATH", str(root))
    kwargs = {}
    if source == "code":
        root = tmp_path / "code"
        kwargs["log_dir"] = root
        monkeypatch.setenv("POLARIS_LOG_PATH", str(tmp_path / "ignored"))
    if source == "file":
        root = tmp_path
        kwargs["file_path"] = tmp_path / "polaris.log"
    base = log.init_log(**kwargs)
    log.info("base entry")
    log.get_logger("network").info("network entry")
    network = log._process_loggers["network"]
    assert Path(network.handlers[0].baseFilename) == root / "network" / "polaris-network.log"
    base_path = root / "polaris.log" if source == "file" else root / "base" / "polaris.log"
    assert Path(base.handlers[0].baseFilename) == base_path
    assert "base entry" in base_path.read_text()
    assert "network entry" not in base_path.read_text()
    assert "network entry" in (root / "network" / "polaris-network.log").read_text()


def test_replacing_process_logger_closes_owned_category_handlers(tmp_path, process_logs):
    log.init_log(log_dir=tmp_path / "first")
    log.get_logger("network").info("first network entry")
    handlers = [handler for instance in log._process_loggers.values() for handler in instance.handlers]
    replacement = log.create_log(log_dir=tmp_path / "second")
    assert log.default_logger is replacement
    assert all(handler.stream is None for handler in handlers)
    log.get_logger("network").info("second network entry")
    network_handler = log._process_loggers["network"].handlers[0]
    application = logging.Logger("application")
    handler = logging.NullHandler()
    application.addHandler(handler)
    log.set_logger(application)
    assert network_handler.stream is None
    assert application.handlers == [handler]
    assert not handler._closed
    assert log._get_logger("network") is application


def test_unknown_log_categories_create_no_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="Unknown log category"):
        log.get_logger("../outside")
    assert list(tmp_path.iterdir()) == []


def _child_log_owner(connection, path, process_logger=False, directory=False):
    try:
        if process_logger:
            instance = log.create_log(file_path=path, max_bytes=200, backup_count=2)
            close = log._close_process_logs
        else:
            options = {"log_dir" if directory else "file_path": path}
            instance = log.ContextLogger(str(uuid4()) if directory else "child",
                                         log.LogOptions(**options, max_bytes=200, backup_count=2))
            close = instance.close
        instance.info("child owns the file")
        connection.send(str(instance.file_path) if directory else "ready")
        connection.recv()
        close()
        connection.send("closed")
    except Exception as error:
        connection.send((type(error).__name__, str(error)))
    finally:
        connection.close()


@pytest.fixture
def child_owner():
    children = []

    def create(path, process_logger=False, directory=False):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=_child_log_owner, args=(child, str(path), process_logger, directory))
        process.start()
        child.close()
        children.append((process, parent))
        assert parent.poll(15), "child did not acquire log files"
        ready = parent.recv()
        if directory:
            return process, parent, Path(ready)
        assert ready == "ready"
        return process, parent

    yield create
    for process, connection in children:
        if process.is_alive():
            process.kill()
        process.join(10)
        connection.close()
        assert not process.is_alive()


@pytest.mark.parametrize("process_logger", [False, True])
@pytest.mark.parametrize("contender_process_logger", [False, True])
def test_cross_process_log_owner_rejects_context_and_process_contenders(
        child_owner, tmp_path, process_logs, process_logger, contender_process_logger):
    path = tmp_path / "shared.log"
    process, connection = child_owner(path, process_logger)
    original = path.read_bytes()
    with pytest.raises(SDKError, match="already in use"):
        if contender_process_logger:
            log.create_log(file_path=path)
        else:
            log.ContextLogger("contender", log.LogOptions(file_path=path))
    assert path.read_bytes() == original
    assert not log._context_log_files
    connection.send("close")
    assert connection.poll(15) and connection.recv() == "closed"
    process.join(10)
    assert process.exitcode == 0
    instance = log.ContextLogger("replacement", log.LogOptions(file_path=path))
    instance.info("replacement owns the file")
    instance.close()
    assert "replacement owns the file" in path.read_text()


@pytest.mark.parametrize("process_logger", [False, True])
def test_cross_process_reserves_lazy_category_paths(child_owner, tmp_path, process_logger):
    child_owner(tmp_path / "shared.log", process_logger)
    path = tmp_path / "network" / "shared-network.log"
    assert not path.exists()
    with pytest.raises(SDKError, match="already in use"):
        log.ContextLogger("contender", log.LogOptions(file_path=path))
    assert not path.exists()


@pytest.mark.parametrize("suffix", [".1", ".6", ".1.2"])
@pytest.mark.parametrize("backup_first", [False, True])
@pytest.mark.parametrize("process_logger", [False, True])
def test_cross_process_rejects_overlapping_backup_namespaces(
        child_owner, tmp_path, process_logger, backup_first, suffix):
    base = tmp_path / "shared.log"
    backup = Path(f"{base}{suffix}")
    owned, contested = (backup, base) if backup_first else (base, backup)
    child_owner(owned, process_logger)
    original = owned.read_bytes()
    with pytest.raises(SDKError, match="already in use"):
        log.ContextLogger("contender", log.LogOptions(file_path=contested))
    assert owned.read_bytes() == original and not contested.exists()


@pytest.mark.parametrize("process_logger", [False, True])
def test_killed_process_releases_log_file_locks(child_owner, tmp_path, process_logger):
    path = tmp_path / "shared.log"
    process, _ = child_owner(path, process_logger)
    process.kill()
    process.join(10)
    assert not process.is_alive()
    replacement = log.ContextLogger("replacement", log.LogOptions(file_path=path))
    try:
        for index in range(8):
            replacement.info("replacement %s %s", index, "x" * 60)
    finally:
        replacement.close()
    assert "replacement 7" in path.read_text()


@pytest.mark.parametrize("context_first", [False, True])
def test_context_and_process_logger_cannot_share_paths(tmp_path, process_logs, context_first):
    path = tmp_path / "shared.log"
    context = None
    try:
        if context_first:
            context = log.ContextLogger("context", log.LogOptions(file_path=path))
            with pytest.raises(SDKError, match="already in use"):
                log.create_log(file_path=path)
        else:
            log.init_log(file_path=path)
            with pytest.raises(SDKError, match="already in use"):
                log.ContextLogger("context", log.LogOptions(file_path=path))
    finally:
        if context is not None:
            context.close()


def test_partial_reservation_failure_releases_already_acquired_locks(tmp_path):
    from polaris.api import _log_file
    first = tmp_path / "a.log"
    second = tmp_path / "z.log"
    owner = _log_file.LogFileLock(second)
    try:
        with pytest.raises(SDKError, match="already in use"):
            _log_file.reserve_log_files([first, second])
        replacement = _log_file.LogFileLock(first)
        replacement.close()
    finally:
        owner.close()


def test_failed_handler_open_releases_all_category_locks(tmp_path, monkeypatch):
    original = log._create_file_logger

    def fail(*args):
        raise OSError("open failed")

    monkeypatch.setattr(log, "_create_file_logger", fail)
    path = tmp_path / "shared.log"
    with pytest.raises(SDKError, match="Cannot open"):
        log.ContextLogger("failed", log.LogOptions(file_path=path))
    monkeypatch.setattr(log, "_create_file_logger", original)
    replacement = log.ContextLogger("replacement", log.LogOptions(file_path=path))
    replacement.close()


def test_replacing_process_logger_same_path_preserves_exclusive_ownership(tmp_path, process_logs):
    path = tmp_path / "shared.log"
    first = log.create_log(file_path=path)
    original_lock = log._process_file_locks[path]
    second = log.create_log(file_path=path, max_bytes=200, backup_count=1)
    assert second is not first
    assert log._process_file_locks[path] is original_lock and original_lock.stream is not None
    with pytest.raises(SDKError, match="already in use"):
        log.ContextLogger("contender", log.LogOptions(file_path=path))
    log._close_process_logs()
    assert original_lock.stream is None


def test_closed_handler_does_not_reopen_after_replacement_takes_path(tmp_path):
    path = tmp_path / "shared.log"
    first = log.ContextLogger("first", log.LogOptions(file_path=path))
    handler = first.handler
    first.close()
    second = log.ContextLogger("second", log.LogOptions(file_path=path))
    try:
        handler.handle(logging.LogRecord("old", logging.INFO, "", 0, "stale entry", (), None))
        second.info("new entry")
    finally:
        second.close()
    assert "stale entry" not in path.read_text() and "new entry" in path.read_text()


def aged_file(path, seconds):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("old log entry", encoding="utf-8")
    timestamp = time.time() - seconds
    os.utime(path, (timestamp, timestamp))
    return path


def test_log_rotation_defaults_follow_go():
    options = log.LogOptions()
    assert (options.max_bytes, options.backup_count, options.max_age_days) == (50 * 1024 * 1024, 5, 30)


@pytest.mark.parametrize("category", ["base", "network"])
def test_context_startup_removes_expired_backups_before_lazy_open(tmp_path, category):
    paths = log._log_paths(log_dir=tmp_path, client_id="client")
    path = paths[category]
    expired = aged_file(Path(f"{path}.1"), 31 * 86400)
    fresh = aged_file(Path(f"{path}.2"), 29 * 86400)
    unrelated = aged_file(Path(f"{path}.notes"), 31 * 86400)
    logger = log.ContextLogger("client", log.LogOptions(log_dir=tmp_path))
    try:
        assert not expired.exists() and fresh.exists() and unrelated.exists()
        if category == "network":
            assert not path.exists()
    finally:
        logger.close()


def test_retention_removes_backups_exceeding_count_on_restart(tmp_path):
    path = tmp_path / "client.log"
    kept = aged_file(Path(f"{path}.2"), 60)
    excess = aged_file(Path(f"{path}.3"), 60)
    logger = log.ContextLogger("client", log.LogOptions(file_path=path, backup_count=2))
    try:
        assert kept.exists() and not excess.exists()
    finally:
        logger.close()


def test_retention_preserves_current_file_even_when_old(tmp_path):
    path = aged_file(tmp_path / "client.log", 31 * 86400)
    logger = log.ContextLogger("client", log.LogOptions(file_path=path))
    try:
        logger._retention.cleanup()
        assert path.exists() and path.read_text() == "old log entry"
        logger.info("live entry")
        assert "live entry" in path.read_text()
    finally:
        logger.close()


def test_default_directory_cleans_expired_uuid_logs_from_previous_contexts(tmp_path):
    old_id, new_id = str(uuid4()), str(uuid4())
    paths = log._log_paths(log_dir=tmp_path, client_id=old_id)
    old_base = aged_file(paths["base"], 31 * 86400)
    old_network = aged_file(paths["network"], 31 * 86400)
    old_backup = aged_file(Path(f"{old_network}.1"), 31 * 86400)
    unrelated = aged_file(tmp_path / "base" / "application.log", 31 * 86400)
    fresh = aged_file(tmp_path / "base" / f"polaris-{uuid4()}.log", 60)
    logger = log.ContextLogger(new_id, log.LogOptions(log_dir=tmp_path))
    try:
        assert not any(path.exists() for path in (old_base, old_network, old_backup))
        assert unrelated.exists() and fresh.exists()
    finally:
        logger.close()


def test_retention_skips_expired_logs_owned_by_another_live_context(tmp_path):
    first = log.ContextLogger(str(uuid4()), log.LogOptions(log_dir=tmp_path))
    backup = aged_file(Path(f"{first.file_path}.1"), 31 * 86400)
    old = time.time() - 31 * 86400
    os.utime(first.file_path, (old, old))
    second = log.ContextLogger(str(uuid4()), log.LogOptions(log_dir=tmp_path))
    try:
        assert first.file_path.exists() and backup.exists()
        first.close()
        second._retention.cleanup()
        assert not first.file_path.exists() and not backup.exists()
    finally:
        first.close()
        second.close()


def test_retention_skips_expired_logs_owned_by_another_process(child_owner, tmp_path):
    process, connection, path = child_owner(tmp_path, directory=True)
    backup = aged_file(Path(f"{path}.1"), 31 * 86400)
    old = time.time() - 31 * 86400
    os.utime(path, (old, old))
    logger = log.ContextLogger(str(uuid4()), log.LogOptions(log_dir=tmp_path))
    try:
        assert path.exists() and backup.exists()
        connection.send("close")
        assert connection.poll(15) and connection.recv() == "closed"
        process.join(10)
        assert process.exitcode == 0
        logger._retention.cleanup()
        assert not path.exists() and not backup.exists()
    finally:
        logger.close()


def test_maintenance_cleans_expired_backups_without_new_entries(tmp_path, monkeypatch):
    from polaris.api import _log_file
    monkeypatch.setattr(_log_file, "CLEANUP_INTERVAL_SECONDS", 0.01)
    logger = log.ContextLogger("client", log.LogOptions(file_path=tmp_path / "client.log"))
    thread = logger._retention.thread
    try:
        backup = aged_file(Path(f"{logger.file_path}.1"), 31 * 86400)
        deadline = time.monotonic() + 5
        while backup.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not backup.exists()
    finally:
        logger.close()
    assert not thread.is_alive()
    assert not logger._file_locks


def test_rotation_records_backup_age_at_rollover(tmp_path):
    logger = log.ContextLogger("client", log.LogOptions(file_path=tmp_path / "client.log",
                                                       max_bytes=200, backup_count=5, max_age_days=1))
    try:
        logger.info("old entry")
        old = time.time() - 2 * 86400
        os.utime(logger.file_path, (old, old))
        logger.info("new entry %s", "x" * 160)
        backup = Path(f"{logger.file_path}.1")
        assert backup.exists() and "old entry" in backup.read_text()
        assert time.time() - backup.stat().st_mtime < 5
        logger._retention.cleanup()
        assert backup.exists()
    finally:
        logger.close()


def test_retention_never_deletes_symbolic_link_targets(tmp_path):
    target = aged_file(tmp_path / "outside.log", 31 * 86400)
    backup = tmp_path / "client.log.1"
    try:
        backup.symlink_to(target)
    except OSError:
        pytest.skip("creating symlinks is unavailable")
    logger = log.ContextLogger("client", log.LogOptions(file_path=tmp_path / "client.log"))
    try:
        assert backup.is_symlink() and target.exists()
    finally:
        logger.close()


def test_retention_failure_is_retried_on_next_scan(tmp_path, monkeypatch, caplog):
    logger = log.ContextLogger("client", log.LogOptions(file_path=tmp_path / "client.log"))
    backup = aged_file(Path(f"{logger.file_path}.1"), 31 * 86400)
    original = Path.unlink

    def fail(path, *args, **kwargs):
        if path == backup:
            raise PermissionError("temporarily busy")
        return original(path, *args, **kwargs)

    try:
        monkeypatch.setattr(Path, "unlink", fail)
        logger._retention.cleanup()
        assert backup.exists() and "Cannot clean expired log file" in caplog.text
        logger.info("still usable")
        monkeypatch.setattr(Path, "unlink", original)
        logger._retention.cleanup()
        assert not backup.exists() and "still usable" in logger.file_path.read_text()
    finally:
        logger.close()


def test_zero_retention_disables_age_cleanup_but_preserves_count_limit(tmp_path):
    path = tmp_path / "client.log"
    kept = aged_file(Path(f"{path}.1"), 31 * 86400)
    excess = aged_file(Path(f"{path}.3"), 60)
    logger = log.ContextLogger("client", log.LogOptions(file_path=path, backup_count=2, max_age_days=0))
    try:
        assert kept.exists() and not excess.exists()
        assert logger._retention.thread is None
    finally:
        logger.close()


@pytest.mark.parametrize("age", [-1, True, 1.5, "30", None])
def test_invalid_retention_options_create_no_files(tmp_path, age):
    with pytest.raises(SDKError, match="rotation options"):
        log.ContextLogger("invalid", log.LogOptions(log_dir=tmp_path / "logs", max_age_days=age))
    assert not (tmp_path / "logs").exists()


def test_code_assigned_retention_is_captured_for_lazy_categories(tmp_path):
    options = log.LogOptions(log_dir=tmp_path)
    options.max_age_days = 2
    logger = log.ContextLogger("client", options)
    try:
        options.max_age_days = 100
        network = logger.get_logger("network")
        assert logger._retention.max_age_days == network.handler.max_age_days == 2
        assert logger.handler.max_age_days == 2
    finally:
        logger.close()


def test_process_logs_share_rotation_and_retention_options(tmp_path, process_logs):
    path = tmp_path / "client.log"
    backup = aged_file(Path(f"{path}.1"), 31 * 86400)
    log.init_log(file_path=path, max_bytes=4096, backup_count=2, max_age_days=7)
    log.get_logger("network").info("network entry")
    retention = log._process_retention
    thread = retention.thread
    assert not backup.exists()
    handlers = [instance.handlers[0] for instance in log._process_loggers.values()]
    assert all((handler.maxBytes, handler.backupCount, handler.max_age_days) == (4096, 2, 7)
               for handler in handlers)
    log.set_logger(logging.Logger("application"))
    assert not thread.is_alive() and not log._process_file_locks
    assert all(handler.stream is None for handler in handlers)


def test_retention_does_not_roll_files_at_day_boundary(tmp_path, monkeypatch):
    from polaris.api import _log_file
    logger = log.ContextLogger("client", log.LogOptions(file_path=tmp_path / "client.log"))
    now = time.time()
    try:
        logger.info("first day")
        monkeypatch.setattr(_log_file.time, "time", lambda: now + 86400)
        logger.info("second day")
        logger._retention.cleanup()
        assert "first day" in logger.file_path.read_text() and "second day" in logger.file_path.read_text()
        assert not Path(f"{logger.file_path}.1").exists()
    finally:
        logger.close()


def test_retention_cutoff_keeps_file_exactly_at_max_age(tmp_path, monkeypatch):
    from polaris.api import _log_file
    now = time.time()
    path = tmp_path / "client.log"
    exact, expired = Path(f"{path}.1"), Path(f"{path}.2")
    for item in (exact, expired):
        item.write_text("log entry", encoding="utf-8")
    cutoff = now - 30 * 86400
    os.utime(exact, (cutoff, cutoff))
    os.utime(expired, (cutoff - 1, cutoff - 1))
    monkeypatch.setattr(_log_file.time, "time", lambda: now)
    logger = log.ContextLogger("client", log.LogOptions(file_path=path))
    try:
        assert exact.exists() and not expired.exists()
    finally:
        logger.close()


def test_log_lock_inode_remains_stable_across_close_and_reopen(tmp_path):
    path = tmp_path / "client.log"
    logger = log.ContextLogger("client", log.LogOptions(file_path=path))
    sidecar = path.with_name(".client.log.lock")
    identity = sidecar.stat().st_ino
    logger.close()
    replacement = log.ContextLogger("replacement", log.LogOptions(file_path=path))
    try:
        assert sidecar.stat().st_ino == identity
    finally:
        replacement.close()


def test_fork_inherited_context_cannot_open_new_category(tmp_path, monkeypatch):
    logger = log.ContextLogger("client", log.LogOptions(log_dir=tmp_path))
    original_pid = os.getpid()
    try:
        monkeypatch.setattr(log.os, "getpid", lambda: original_pid + 1)
        with pytest.raises(SDKError, match="after fork"):
            logger.get_logger("network")
        logger.info("inherited entry")
        assert "inherited entry" not in logger.file_path.read_text()
    finally:
        monkeypatch.undo()
        logger.close()


def test_failed_retention_start_releases_handlers_and_locks(tmp_path, monkeypatch):
    from polaris.api import _log_file

    def fail(thread):
        raise RuntimeError("thread start failed")

    original = _log_file.Thread.start
    monkeypatch.setattr(_log_file.Thread, "start", fail)
    path = tmp_path / "client.log"
    with pytest.raises(RuntimeError, match="thread start failed"):
        log.ContextLogger("failed", log.LogOptions(file_path=path))
    monkeypatch.setattr(_log_file.Thread, "start", original)
    replacement = log.ContextLogger("replacement", log.LogOptions(file_path=path))
    replacement.close()
