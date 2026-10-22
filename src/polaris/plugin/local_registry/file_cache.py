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
import os
import tempfile
import time
from concurrent.futures import Future, ThreadPoolExecutor
from queue import Queue
from threading import Event, Lock, Thread
from urllib.parse import quote_plus

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows CI
    fcntl = None

from google.protobuf import json_format
from google.protobuf.message import DecodeError
from polarismesh_specification.api.v1.service_manage import response_pb2

from polaris.api.log import ContextLogger, get_logger
from polaris.pkg.config.api import LocalCacheConfig
from polaris.pkg.config.default import DefaultConf
from polaris.pkg.model.server import InstanceDiscoverRequest
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.plugin_manager import PluginType
from polaris.plugin_manager import register_plugin

LOCK_FILE = "file_cache.lock"
CACHE_FILE_SUFFIX = ".json"
CACHE_READ_ERRORS = (OSError, DecodeError, json_format.ParseError, UnicodeDecodeError)
DISCOVER_TYPE_FILE_NAMES = {
    1: "instance",
}
logger = get_logger("cache")


class BackupTaskMsg:
    def __init__(self, service: InstanceDiscoverRequest, data: response_pb2.DiscoverResponse | None,
                 completion: Future | None = None):
        self.service = service
        self.data = data
        self.completion = completion


@register_plugin(PluginType.LOCAL_CACHE, 'file')
class LocalFileCache:
    """Own a disk backup queue, lock and writer thread for one context."""

    def __init__(self, init_ctx=None, base_dir=None):
        cache_config = LocalCacheConfig()
        cache_config.set_default()
        if init_ctx is not None:
            cache_config = init_ctx.config.get_consumer().get_local_cache()
        if base_dir is None:
            base_dir = cache_config.get_persist_dir()
        self.max_write_retry = cache_config.get_persist_max_write_retry()
        self.max_read_retry = cache_config.get_persist_max_read_retry()
        self.retry_interval = cache_config.get_persist_retry_interval() / 1000
        context_logger = getattr(init_ctx, "logger", None)
        self.logger = (context_logger.get_logger("cache") if isinstance(context_logger, ContextLogger)
                       else context_logger or logger)
        self.base_dir = os.path.expandvars(
            os.path.expanduser(base_dir or DefaultConf.DefaultCachePersistDir)
        )
        os.makedirs(self.base_dir, exist_ok=True)
        lock_file_path = os.path.join(self.base_dir, LOCK_FILE)
        self.lock_file = open(lock_file_path, 'a+')
        self.thread_lock = Lock()
        self._state_lock = Lock()
        self._close_lock = Lock()
        self._closed = False
        self._closing = Event()
        self._read_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="polaris-cache-read")

        self.queue = Queue()
        self.write_thread = Thread(target=self.thread_loop, daemon=True)
        self.write_thread.start()

    def _lock(self):
        """
        write lock (contention is retried outside the critical section)
        :return:
        """
        if not self.thread_lock.acquire(blocking=False):
            raise BlockingIOError("cache backup is busy")
        try:
            if fcntl is not None:
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.thread_lock.release()
            raise
        return True

    def thread_loop(self):
        self.logger.warning("start backup threading")
        while True:
            msg: BackupTaskMsg = self.queue.get()
            try:
                if msg is None:
                    return
                if msg.completion is not None:
                    msg.completion.set_running_or_notify_cancel()
                if msg.data is None:
                    operation = lambda: self._delete(msg.service)
                else:
                    operation = lambda: self._save(msg.service, msg.data)
                self._retry(operation, self.max_write_retry)
                if msg.completion is not None and not msg.completion.done():
                    msg.completion.set_result(None)
            except Exception as error:
                operation = "delete" if msg.data is None else "write"
                self.logger.error("failed to %s cache backup: %s", operation, error)
                if msg.completion is not None and not msg.completion.done():
                    msg.completion.set_exception(error)
            finally:
                self.queue.task_done()

    def _share_lock(self):
        """
        read lock
        :return:
        """
        if not self.thread_lock.acquire(blocking=False):
            return False
        if self._closed:
            self.thread_lock.release()
            return False
        if fcntl is not None:
            try:
                fcntl.flock(self.lock_file, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError:
                self.thread_lock.release()
                return False
        return True

    def _unlock(self):
        try:
            if fcntl is not None:
                fcntl.flock(self.lock_file, fcntl.LOCK_UN)
        finally:
            self.thread_lock.release()

    def _retry(self, operation, max_retry, reading=False):
        for attempt in range(max_retry + 1):
            if reading and self._closed:
                return None
            try:
                return operation()
            except CACHE_READ_ERRORS as error:
                if attempt == max_retry:
                    raise
                self.logger.warning("cache backup failed; retry %d/%d: %s", attempt + 1, max_retry, error)
                if reading:
                    if self._closing.wait(self.retry_interval):
                        return None
                else:
                    time.sleep(self.retry_interval)

    def destroy(self):
        """Drain accepted writes, stop the writer, then release its file descriptor."""
        with self._close_lock:
            with self._state_lock:
                if not self._closed:
                    self._closed = True
                    self._closing.set()
                    self.queue.put(None)
            # Accepted writes retain their retry budget, which can exceed five seconds.
            self.write_thread.join()
            self._read_executor.shutdown(wait=True, cancel_futures=True)
            with self.thread_lock:
                self.lock_file.close()

    def save(self, service: InstanceDiscoverRequest, data: response_pb2.DiscoverResponse):
        """Queue a private snapshot while this context's backup writer is open."""
        with self._state_lock:
            if self._closed:
                raise SDKError(ErrorCode.ErrCodeInvalidStateError, "File cache has been destroyed")
            snapshot = self._copy_response(data)
            request = self._copy_request(service)
            self.queue.put(BackupTaskMsg(request, snapshot))

    def _copy_request(self, service):
        return InstanceDiscoverRequest(service.type, service.name, service.namespace)

    def _copy_response(self, data):
        snapshot = response_pb2.DiscoverResponse()
        snapshot.CopyFrom(data)
        return snapshot

    def _parse_response(self, service, buf):
        return json_format.Parse(buf.decode("utf-8"), response_pb2.DiscoverResponse())

    async def delete(self, service: InstanceDiscoverRequest):
        """Delete a backup after earlier queued writes without blocking the owner loop."""
        completion = Future()
        with self._state_lock:
            if self._closed:
                raise SDKError(ErrorCode.ErrCodeInvalidStateError, "File cache has been destroyed")
            request = InstanceDiscoverRequest(service.type, service.name, service.namespace)
            self.queue.put(BackupTaskMsg(request, None, completion))
        await asyncio.wrap_future(completion)

    def _delete(self, service: InstanceDiscoverRequest):
        self._lock()
        try:
            try:
                os.remove(self.get_cache_file_path(service))
            except FileNotFoundError:
                pass
        finally:
            self._unlock()

    def _save(self, service: InstanceDiscoverRequest, data: response_pb2.DiscoverResponse):
        temporary_path = None
        file_path = self.get_cache_file_path(service)
        self._lock()
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.base_dir,
                                             prefix=os.path.basename(file_path) + ".", suffix=".tmp",
                                             delete=False) as data_file:
                temporary_path = data_file.name
                data_file.write(
                    json_format.MessageToJson(
                        data,
                        indent=2,
                        sort_keys=True,
                    ).encode("utf-8")
                )
                data_file.flush()
                os.fsync(data_file.fileno())
            os.replace(temporary_path, file_path)
            temporary_path = None
            self.logger.warning("success to back up data for %s", service.name)
        finally:
            try:
                if temporary_path is not None:
                    os.unlink(temporary_path)
            finally:
                self._unlock()

    def get(self, service: InstanceDiscoverRequest, expire: int | None = 60) -> response_pb2.DiscoverResponse | None:
        """Read a snapshot with configured retries. ``expire=None`` ignores file modification time."""
        if self._closed:
            return None
        try:
            return self._retry(lambda: self._read(service, expire), self.max_read_retry, reading=True)
        except CACHE_READ_ERRORS as error:
            self.logger.error("failed to read cache backup for %s: %s", service.name, error)
            return None

    async def async_get(self, service: InstanceDiscoverRequest, expire: int | None = 60):
        """Read a backup on this context's reader without blocking its owner loop."""
        with self._state_lock:
            if self._closed:
                return None
            future = self._read_executor.submit(self.get, service, expire)
        return await asyncio.wrap_future(future)

    def _read(self, service, expire):
        file_path = self.get_cache_file_path(service)
        if not self._share_lock():
            raise BlockingIOError("cache backup is busy")
        try:
            if self._closed:
                return None
            try:
                with open(file_path, "rb") as data_file:
                    if expire is not None and time.time() - os.fstat(data_file.fileno()).st_mtime > expire:
                        return None
                    buf = data_file.read()
            except FileNotFoundError:
                return None
            if not buf:
                raise DecodeError("empty cache backup")
            return self._parse_response(service, buf)
        finally:
            self._unlock()

    @staticmethod
    def _get_cache_file_name(service: InstanceDiscoverRequest) -> str:
        type_name = DISCOVER_TYPE_FILE_NAMES.get(service.type)
        if type_name is None:
            raise SDKError(
                ErrorCode.ErrCodeAPIInvalidArgument,
                "unsupported discover request type: %s" % service.type,
            )
        return "svc#%s#%s#%s%s" % (
            quote_plus(service.namespace, safe=""),
            quote_plus(service.name, safe=""),
            type_name,
            CACHE_FILE_SUFFIX,
        )

    def get_cache_file_path(self, service: InstanceDiscoverRequest) -> str:
        file_name = self._get_cache_file_name(service)
        return os.path.join(self.base_dir, file_name)
