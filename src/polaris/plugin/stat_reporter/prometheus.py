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

"""Java-compatible period gauges and Prometheus pull / Pushgateway export."""

import asyncio
import gzip
import random
import re
from threading import RLock
from urllib.parse import quote, urlsplit, urlunsplit

from aiohttp import ClientSession, ClientTimeout, web
from prometheus_client import CollectorRegistry, Gauge, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST

from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.pkg.config import stat_reporter as stat_reporter_config
from polaris.pkg.model.service import GetOneInstanceRequest, RetStatus
from polaris.plugin_manager import PluginType, register_plugin
from .base import BaseStatReporter

LABELS = ("callee_namespace", "callee_service", "callee_method", "callee_instance",
          "callee_instance_type", "callee_result_code", "callee_result", "caller_labels",
          "caller_namespace", "caller_service", "caller_ip", "metric_name")
METRICS = {
    "upstream_rq_total": "total of request per period",
    "upstream_rq_success": "total of success request per period",
    "upstream_rq_timeout": "total of request delay per period",
    "upstream_rq_max_timeout": "maximum request delay per period",
    "upstream_rq_min_timeout": "minimum request delay per period",
}
PULL_INTERVAL_SECONDS = 30
NULL = "__NULL__"


@register_plugin(PluginType.STAT_REPORTER, "prometheus")
class PrometheusReporter(BaseStatReporter):
    """Own independent metrics, HTTP listener and push task for one context."""

    def __init__(self, init_ctx):
        self.global_config = init_ctx.config.get_global()
        self.config = self.global_config.get_stat_reporter().get_prometheus()
        self.enabled = self.global_config.get_stat_reporter().is_enable()
        self.client_id = init_ctx.value_ctx.get_client_id()
        from polaris.api.log import get_logger
        self.logger = init_ctx.logger.get_logger("statReport") if init_ctx.logger else get_logger("statReport")
        self.registry = CollectorRegistry()
        self.gauges = {name: Gauge(name, description, LABELS, registry=self.registry)
                       for name, description in METRICS.items()}
        self.lock = RLock()
        self.period = 0
        self.values = {}
        self.task = None
        self.runner = None
        self.session = None
        self.port = None
        self.engine = None
        self.closed = False
        self.random = random.Random()
        self.push_lock = asyncio.Lock()
        self.pushing = False

    def report(self, result):
        """Record Java label values and period count / delay aggregations."""
        if not self.enabled or self.closed:
            return
        method = result.method
        if method:
            for pattern in self.config.path_regex_list:
                if re.fullmatch(pattern, method):
                    method = pattern
                    break
        caller = result.caller_service
        ip = result.caller_ip
        if ip is None:
            ip = self.global_config.get_api().get_bind_ip()
        labels = (result.get_namespace(), result.get_service(), method,
                  f"{result.get_host()}:{result.get_port()}", result.instance_type,
                  result.ret_code, RetStatus.descriptions[result.ret_status], result.labels,
                  caller.get_namespace() if caller else None,
                  caller.get_service() if caller else None, ip)
        key = tuple(NULL if item is None else str(item) for item in labels)
        delay = result.delay or 0
        success = int(result.ret_status == RetStatus.RetSuccess)
        with self.lock:
            period = self.period + int(self.pushing)
            existing = self.values.get(key)
            if existing is None or existing[0] != period:
                self.values[key] = (period, [1, success, delay, delay, delay])
            else:
                values = existing[1]
                values[0] += 1
                values[1] += success
                if result.delay is not None:
                    values[2] += delay
                    values[3] = max(values[3], delay)
                    values[4] = min(values[4], delay)

    def aggregate(self, advance=True):
        """Publish this period, zero stale series, remove after two idle revisions."""
        with self.lock:
            for key, (revision, values) in list(self.values.items()):
                for name, value in zip(METRICS, values):
                    labels = (*key, NULL)
                    if revision < self.period - 2:
                        self.gauges[name].remove(*labels)
                    else:
                        self.gauges[name].labels(*labels).set(value if revision == self.period else 0)
                if revision < self.period - 2:
                    del self.values[key]
            if advance:
                self.period += 1

    def render(self):
        """Return the current exported Prometheus text without advancing the period."""
        with self.lock:
            return generate_latest(self.registry)

    def meta_info(self):
        """Advertise the pull endpoint in the SDK client report, never in push mode."""
        if not self.enabled or self.closed or self.port is None or self.config.type != "pull":
            return None
        return {"target": "prometheus", "port": self.port, "path": self.config.path, "protocol": "http"}

    async def start(self, engine):
        """Start pull or push resources after the SDK address is resolved."""
        self.engine = engine
        if not self.enabled:
            return
        admin = self.global_config.get_admin()
        if self.config.type == "pull":
            if admin.port < 0:
                self.enabled = False
                return
            app = web.Application()
            app.router.add_get(self.config.path, self._metrics)
            if self.config.path != "/-/healthy":
                app.router.add_get("/-/healthy", self._metrics)
            self.runner = web.AppRunner(app, access_log=None)
            await self.runner.setup()
            listen_port = (admin.port if admin.port is not None
                           else stat_reporter_config.DEFAULT_ADMIN_PORT)
            site = web.TCPSite(self.runner, admin.host, listen_port)
            try:
                await site.start()
            except OSError as error:
                await self.runner.cleanup()
                self.runner = None
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig,
                               f"Cannot bind metrics listener {admin.host}:{admin.port}: {error}") from error
            self.port = site._server.sockets[0].getsockname()[1]
        else:
            self.session = ClientSession(timeout=ClientTimeout(total=self.global_config.get_api().timeout / 1000))
        self.task = asyncio.create_task(self._run(), name="polaris-prometheus")

    async def _metrics(self, request):
        return web.Response(body=self.render(), headers={"Content-Type": CONTENT_TYPE_LATEST})

    async def _address(self):
        if self.config.address:
            return self.random.choice(self.config.address)
        monitor = self.global_config.get_system().get_monitor_cluster()
        namespace = monitor.get_namespace() or self.config.namespace
        service = monitor.get_service() or self.config.service
        node = await self.engine._async_get_one_instance(GetOneInstanceRequest(
            namespace=namespace, service=service))
        if node is None:
            raise SDKError(ErrorCode.ErrCodeAPIInstanceNotFound, "No Pushgateway instance available")
        host = node.get_host()
        return f"[{host}]:{node.get_port()}" if ":" in host else f"{host}:{node.get_port()}"

    async def push(self):
        """POST gauges using Java job / grouping keys; failures retain the current period."""
        async with self.push_lock:
            await self._push()

    async def _push(self):
        address = await self._address()
        url = urlsplit(address if "://" in address else f"http://{address}")
        if self.config.override_host:
            host = self.config.override_host
            netloc = f"[{host}]" if ":" in host else host
            if url.port:
                netloc += f":{url.port}"
            url = url._replace(netloc=netloc)
        target = urlunsplit(url._replace(path=url.path.rstrip("/") +
                           f"/metrics/job/polaris-client/instance/{quote(self.client_id, safe='')}", query=""))
        with self.lock:
            self.aggregate(advance=False)
            data = self.render()
            snapshot = {key: (revision, list(values)) for key, (revision, values) in self.values.items()}
            self.pushing = True
        headers = {"Content-Type": CONTENT_TYPE_LATEST}
        if self.config.open_gzip:
            data = gzip.compress(data)
            headers["Content-Encoding"] = "gzip"
        try:
            async with self.session.post(target, data=data, headers=headers) as response:
                await response.read()
                if not 200 <= response.status < 300:
                    raise SDKError(ErrorCode.ErrCodeNetworkError, f"Pushgateway returned HTTP {response.status}")
        except BaseException:
            with self.lock:
                for key, (revision, values) in list(self.values.items()):
                    if revision != self.period + 1:
                        continue
                    previous = snapshot.get(key)
                    if previous is not None and previous[0] == self.period:
                        old = previous[1]
                        values = [old[0] + values[0], old[1] + values[1], old[2] + values[2],
                                  max(old[3], values[3]), min(old[4], values[4])]
                    self.values[key] = (self.period, values)
            raise
        else:
            with self.lock:
                self.period += 1
        finally:
            with self.lock:
                self.pushing = False

    async def _run(self):
        interval = self.config.push_interval / 1000 if self.config.type == "push" else PULL_INTERVAL_SECONDS
        while True:
            await asyncio.sleep(interval)
            try:
                if self.config.type == "push":
                    await self.push()
                else:
                    self.aggregate()
            except Exception as error:
                self.logger.warning("Metrics export failed; retaining current period: %s", error)

    async def close(self):
        """Cancel the task before closing its listener and outgoing HTTP session."""
        self.closed = True
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None
        if self.session is not None:
            await self.session.close()
            self.session = None
