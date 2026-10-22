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

"""Exclusive file ownership for SDK rotating logs."""

import errno
import logging
import os
import re
import stat
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Event, RLock, Thread

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows CI
    fcntl = None
    import msvcrt

from polaris.pkg.model.error import ErrorCode, SDKError

DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5
DEFAULT_MAX_AGE_DAYS = 30
CLEANUP_INTERVAL_SECONDS = 3600
_UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_maintenance_logger = logging.getLogger("polaris.log.maintenance")


class LogFileLock:
    """Exclusively own a base file and its numbered backup namespace."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.stream = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path
        # Explicit numbered filenames must not overlap another logger's backups.
        while re.fullmatch(r"\.[1-9][0-9]*", lock_path.suffix):
            lock_path = lock_path.with_suffix("")
        stream = lock_path.with_name(f".{lock_path.name}.lock").open("a+b")
        try:
            if fcntl is not None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:  # pragma: no cover - Windows CI
                if os.fstat(stream.fileno()).st_size == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            stream.close()
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig,
                               f"Log file is already in use: {self.path}") from error
            raise
        self.stream = stream

    def close(self):
        """Release ownership without unlinking the lock inode used by other processes."""
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def reserve_log_files(paths, retained=None):
    """Reserve all category paths atomically, retaining a process logger's own locks."""
    retained = retained or {}
    locks = {}
    acquired = []
    try:
        for path in sorted(set(paths)):
            lock = retained.get(path)
            if lock is None:
                lock = LogFileLock(path)
                acquired.append(lock)
            locks[path] = lock
    except Exception:
        for lock in reversed(acquired):
            lock.close()
        raise
    return locks


class ExclusiveRotatingFileHandler(RotatingFileHandler):
    """Do not reopen a closed handler or write through a fork-inherited handler."""

    def __init__(self, *args, max_age_days=DEFAULT_MAX_AGE_DAYS, **kwargs):
        self.owner_pid = os.getpid()
        self.max_age_days = max_age_days
        super().__init__(*args, **kwargs)

    def emit(self, record):
        if not self._closed and self.owner_pid == os.getpid():
            super().emit(record)

    def doRollover(self):
        """Keep numbered backups while recording their age from the rotation time."""
        super().doRollover()
        if self.backupCount > 0:
            try:
                os.utime(f"{self.baseFilename}.1", None)
            except OSError as error:
                _maintenance_logger.warning("Cannot update rotated log age: %s", error)
        cutoff = time.time() - self.max_age_days * 86400 if self.max_age_days else None
        _cleanup_backups(Path(self.baseFilename), cutoff, self.backupCount)


def _remove_file(path, cutoff=None):
    try:
        info = path.stat(follow_symlinks=False)
        if stat.S_ISREG(info.st_mode) and (cutoff is None or info.st_mtime < cutoff):
            path.unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        _maintenance_logger.warning("Cannot clean expired log file %s: %s", path, error)


def _cleanup_backups(base, cutoff, backup_count=0):
    pattern = re.compile(re.escape(base.name) + r"\.([1-9][0-9]*)")
    try:
        for path in base.parent.iterdir():
            match = pattern.fullmatch(path.name)
            if match:
                if backup_count > 0 and int(match[1]) > backup_count:
                    _remove_file(path)
                elif cutoff is not None:
                    _remove_file(path, cutoff)
    except OSError as error:
        _maintenance_logger.warning("Cannot scan log backups for %s: %s", base, error)


class LogRetention:
    """Clean owned backups and expired, inactive UUID-named context files."""

    def __init__(self, locks, max_age_days, backup_count, family_paths=()):
        self.locks = locks
        self.max_age_days = max_age_days
        self.backup_count = backup_count
        self.family_paths = tuple(family_paths)
        self.handlers = {}
        self.lock = RLock()
        self.stopping = Event()
        self.thread = None
        self.owner_pid = os.getpid()

    def add_handler(self, handler):
        """Serialize lazy handler creation with maintenance of its numbered backups."""
        with self.lock:
            self.handlers[Path(handler.baseFilename)] = handler

    def _inactive_files(self):
        candidates = set()
        for family in self.family_paths:
            pattern = re.compile("(" + re.escape(family.stem) + "-" + _UUID_PATTERN
                                 + re.escape(family.suffix) + r")(?:\.[1-9][0-9]*)?")
            try:
                for path in family.parent.iterdir():
                    match = pattern.fullmatch(path.name)
                    if match:
                        candidates.add(path.with_name(match[1]))
            except FileNotFoundError:
                pass
            except OSError as error:
                _maintenance_logger.warning("Cannot scan context logs in %s: %s", family.parent, error)
        return candidates - self.locks.keys()

    def cleanup(self):
        """Skip active owners and symlinks; retry failed deletions on the next scan."""
        if self.owner_pid != os.getpid():
            return
        with self.lock:
            cutoff = time.time() - self.max_age_days * 86400 if self.max_age_days else None
            for path in self.locks:
                handler = self.handlers.get(path)
                if handler is not None:
                    handler.acquire()
                try:
                    _cleanup_backups(path, cutoff, self.backup_count)
                finally:
                    if handler is not None:
                        handler.release()
            if cutoff is None:
                return
            for path in self._inactive_files():
                if path.is_symlink():
                    continue
                try:
                    owner = LogFileLock(path)
                except SDKError:
                    continue
                except OSError as error:
                    _maintenance_logger.warning("Cannot lock inactive log %s: %s", path, error)
                    continue
                try:
                    _cleanup_backups(path, cutoff)
                    _remove_file(path, cutoff)
                finally:
                    owner.close()

    def start(self):
        """Clean on startup, then hourly even if no log entries are emitted."""
        self.cleanup()
        if self.max_age_days:
            thread = Thread(target=self._run, name="polaris-log-retention", daemon=True)
            thread.start()
            self.thread = thread

    def _run(self):
        while not self.stopping.wait(CLEANUP_INTERVAL_SECONDS):
            self.cleanup()

    def close(self):
        """Finish maintenance before the caller closes handlers and releases locks."""
        self.stopping.set()
        if self.thread is not None and self.owner_pid == os.getpid():
            self.thread.join()
