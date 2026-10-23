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
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Batch SDK events and report them to the Polaris event Pushgateway."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import random
from urllib.parse import urlsplit, urlunsplit

from aiohttp import ClientSession, ClientTimeout

from polaris.pkg.model.context import ContextKeyEventCenter
from polaris.pkg.model.event import is_remote_reportable
from polaris.pkg.model.service import GetOneInstanceRequest
from polaris.plugin_manager import PluginType, register_plugin


def _event_payload(event):
    """Convert the public event to the flat wire fields used by Java and Go."""
    return {
        "event_type": event.event_type,
        "event_name": event.event_name,
        "event_time": datetime.fromtimestamp(event.timestamp / 1000).isoformat(timespec="milliseconds"),
        "client_id": event.client_id,
        "client_ip": event.client_ip,
        "namespace": event.namespace,
        "service": event.service,
        "instance_id": event.instance_id,
        "host": event.host,
        "port": str(event.port) if event.port else "",
        "previous_status": event.previous_status,
        "current_status": event.current_status,
        "resource_type": "INSTANCE",
        "rule_name": event.rule_name,
        "reason": event.reason,
        "additional_params": event.additional,
    }


@register_plugin(PluginType.EVENT_REPORTER, "pushgateway")
class PushGatewayEventReporter:
    """Own one context-local event queue, batching task and HTTP session."""

    def __init__(self, init_ctx):
        reporter = init_ctx.config.get_global().get_event_reporter()
        self.config = reporter.get_pushgateway()
        self.enabled = reporter.is_enable() and "pushgateway" in reporter.get_chain()
        self.value_context = init_ctx.value_ctx
        self.logger = init_ctx.logger.get_logger("event") if init_ctx.logger is not None else None
        self.engine = None
        self.queue = None
        self.task = None
        self.session = None
        self.stopping = None
        self.closed = False
        self.random = random.Random()

    def on_sdk_event(self, event):
        """Enqueue one Java-reportable event without blocking SDK control flow."""
        if not self.enabled or self.closed or self.queue is None or not is_remote_reportable(event):
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            if self.logger is not None:
                self.logger.warning("event Pushgateway queue is full; dropping %s", event.event_name)

    async def start(self, engine):
        """Create queue resources and subscribe on the context owner loop."""
        if not self.enabled:
            return
        self.engine = engine
        self.queue = asyncio.Queue(maxsize=self.config.event_queue_size)
        self.stopping = asyncio.Event()
        self.session = ClientSession(timeout=ClientTimeout(total=3))
        event_center = self.value_context.core_map.get(ContextKeyEventCenter)
        if event_center is not None:
            event_center.register_listener(self)
        self.task = asyncio.create_task(self._run(), name="polaris-event-pushgateway")

    async def _run(self):
        interval = self.config.push_interval / 1000
        while not self.closed:
            try:
                await asyncio.wait_for(self.stopping.wait(), interval)
            except TimeoutError:
                pass
            await self._flush_batches()
            if self.stopping.is_set():
                return

    async def _address(self):
        if self.config.address:
            address = self.random.choice(self.config.address)
        else:
            node = await self.engine._async_get_one_instance(GetOneInstanceRequest(
                namespace=self.config.namespace, service=self.config.service))
            if node is None:
                raise RuntimeError("No event Pushgateway instance available")
            host = node.get_host()
            address = f"[{host}]:{node.get_port()}" if ":" in host else f"{host}:{node.get_port()}"
        url = urlsplit(address if "://" in address else f"http://{address}")
        host = self.config.override_host or url.hostname
        netloc = f"[{host}]" if ":" in host else host
        if url.port:
            netloc += f":{url.port}"
        return urlunsplit((url.scheme or "http", netloc, self.config.report_path, "", ""))

    def _log_post(self, level, message, *args):
        if self.logger is None:
            return
        getattr(self.logger, level)(message, *args)

    def _log_post_events(self, level, events, prefix, error=None):
        """Record one line per event, including the same text as the local event log."""
        for event in events:
            detail = event.to_log_message()
            if error is None:
                self._log_post(level, "%s: %s", prefix, detail)
            else:
                self._log_post(level, "%s: %s: %s", prefix, detail, error)

    async def _post(self, events):
        body = json.dumps({"batch": [_event_payload(event) for event in events]},
                          ensure_ascii=False, separators=(",", ":"))
        try:
            target = await self._address()
        except Exception as error:
            self._log_post_events("warning", events, "failed to report event to Pushgateway", error)
            raise
        last_error = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                async with self.session.post(
                        target, data=body.encode("utf-8"), headers={"Content-Type": "application/json"}) as response:
                    await response.read()
                    if not 200 <= response.status < 300:
                        raise RuntimeError(f"Pushgateway returned HTTP {response.status}")
                self._log_post_events("info", events, "reported event to Pushgateway")
                return
            except Exception as error:
                last_error = error
                self._log_post_events(
                    "warning", events,
                    f"failed to report event to Pushgateway (attempt {attempt}/{self.config.max_retries})",
                    error)
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_interval / 1000)
        raise last_error

    async def _flush_batches(self):
        while self.queue is not None and not self.queue.empty():
            events = []
            while len(events) < self.config.max_batch_size:
                try:
                    events.append(self.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            if not events:
                return
            try:
                await self._post(events)
            except Exception:
                pass

    async def close(self):
        """Stop consuming, flush accepted events, and close the HTTP session."""
        if self.closed:
            return
        self.closed = True
        event_center = self.value_context.core_map.get(ContextKeyEventCenter) if self.value_context else None
        if event_center is not None:
            event_center.unregister_listener(self)
        if self.stopping is not None:
            self.stopping.set()
        if self.task is not None:
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        if self.session is not None:
            await self.session.close()
            self.session = None

    def destroy(self):
        """Synchronous plugin lifecycle hook; async resources close with the engine."""
        return None
