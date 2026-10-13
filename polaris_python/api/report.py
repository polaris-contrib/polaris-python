"""Periodic ``ReportClient`` calls, as in polaris-java ``SDKContext.reportClient``."""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import socket
import uuid
from importlib.metadata import PackageNotFoundError, version

from google.protobuf.message import Message
from polarismesh_specification.api.v1.service_manage import client_pb2, response_pb2

from polaris_python.core.config import Config
from polaris_python.core.error import ensure_success
from polaris_python.plugin.connector import ServerConnector

logger = logging.getLogger(__name__)

DEFAULT_ADDRESS = "127.0.0.1"
REPORT_INTERVAL_SECONDS = 60.0
_CLIENT_SEQ = itertools.count()


def sdk_version() -> str:
    """Return the installed ``polaris-python`` version reported to Polaris."""
    try:
        return version("polaris-python")
    except PackageNotFoundError:
        return "unknown"


class ClientReporter:
    """Report this SDK client to Polaris every 60 seconds.

    The request carries the client address, SDK version and client id
    ``<hostname>_<pid>_<seq>``, like Java. The address is ``bind_ip``, or the
    local address of a TCP connection to the first server, or ``127.0.0.1``,
    resolved once. Failures are logged and retried at the next interval.
    """

    def __init__(self, config: Config, connector: ServerConnector) -> None:
        self._config = config
        self._connector = connector
        self.client_id = _client_id(config.bind_ip or DEFAULT_ADDRESS)
        self.host: str | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start reporting on the running event loop; no-op when disabled, already running, or outside a loop."""
        if not self._config.report_enable or (self._task is not None and not self._task.done()):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._report_loop(), name="polaris-report-client")

    async def close(self) -> None:
        """Stop the reporting task."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        if task.get_loop() is asyncio.get_running_loop():
            await asyncio.gather(task, return_exceptions=True)

    async def report_once(self) -> response_pb2.Response | None:
        """Send one ``ReportClient`` request and return the response, or ``None`` when it failed."""
        if self.host is None:
            self.host = await _local_host(self._config)
        client = client_pb2.Client(
            host={"value": self.host},
            version={"value": sdk_version()},
            id={"value": self.client_id},
        )
        try:
            response = await self._connector.report_client(client)
            if isinstance(response, Message):
                ensure_success(response)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Report client failed: %s", exc)
            return None
        location = response.client.location
        logger.debug(
            "Report client success: host=%s id=%s region=%r zone=%r campus=%r",
            self.host,
            self.client_id,
            location.region.value,
            location.zone.value,
            location.campus.value,
        )
        return response

    async def _report_loop(self) -> None:
        loop = asyncio.get_running_loop()
        next_report = loop.time()
        while True:
            await self.report_once()
            next_report += REPORT_INTERVAL_SECONDS
            await asyncio.sleep(max(0.0, next_report - loop.time()))


def _client_id(host: str) -> str:
    try:
        name = socket.gethostname() or host
    except OSError:
        name = host
    if name.lower() == DEFAULT_ADDRESS:
        return str(uuid.uuid4())
    return f"{name}_{os.getpid()}_{next(_CLIENT_SEQ)}"


async def _local_host(config: Config) -> str:
    if config.bind_ip:
        return config.bind_ip
    if not config.server_addresses:
        return DEFAULT_ADDRESS
    host, _, port = config.server_addresses[0].rpartition(":")
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), config.timeout_seconds)
    except (OSError, ValueError, asyncio.TimeoutError) as exc:
        logger.info("[ReportClient] get address by dial failed: %s", exc)
        return DEFAULT_ADDRESS
    try:
        return str(writer.get_extra_info("sockname")[0])
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
