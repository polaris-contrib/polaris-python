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

import time

from .base import BaseCircuitBreaker, CircuitBreakResult
from ...pkg.model.service import Instance, CBStatusEnum
from ...pkg.model.stat import Bucket
from typing import List
from . import config
from polaris.plugin_manager import InitContext, EventType, PluginType, register_plugin
from polaris.pkg.model.stat import SlidingWindow
from polaris.api.log import get_logger

logger = get_logger("circuitbreaker")


class PluginConfig:
    def __init__(self, continuous_err_threshold=config.DefaultOptions.DefaultContinuousErrorThreshold,
                 metric_stat_time_window=config.DefaultOptions.DefaultMetricStatWindow,
                 metric_num_bucket=config.DefaultOptions.DefaultMetricBucketCount,
                 sleep_window=config.DefaultOptions.DefaultSleepTime,
                 request_count_after_halfopen=config.DefaultOptions.DefaultRequestCountAfterHalfOpen,
                 success_count_after_halfopen=config.DefaultOptions.DefaultSuccessCountAfterHalfOpen,
                 err_rate_threshold=config.DefaultOptions.DefaultErrRateThreshold,
                 err_rate_request_threshold=config.DefaultOptions.DefaultErrRateRequestThreshold):
        # 连续失败数量
        self.continuous_error_threshold = continuous_err_threshold
        self.metric_stat_time_window = metric_stat_time_window
        # bucket数量
        self.metric_num_bucket = metric_num_bucket
        # 熔断后多久转为半开
        self.sleep_window = sleep_window
        self.request_count_after_halfopen = request_count_after_halfopen
        # 半开后多少请求后可以转为恢复
        self.success_count_after_halfopen = success_count_after_halfopen

        # 失败率
        self.err_rate_threshold = err_rate_threshold
        self.err_rate_request_threshold = err_rate_request_threshold


class InstanceMetrics:
    """Per-trigger counters, mirroring Java composite TriggerCounter state."""

    def __init__(self, options: PluginConfig):
        self.window = SlidingWindow(options.metric_num_bucket,
                                    (options.metric_stat_time_window + options.metric_num_bucket - 1)
                                    // options.metric_num_bucket)
        self.consecutive_errors = 0
        self.consecutive_suspended = False
        self.consecutive_triggered = False
        self.error_rate_suspended = False
        self.error_rate_check_at = None


@register_plugin(PluginType.CIRCUIT_BREAKER, "composite")
class CircuitBreaker(BaseCircuitBreaker):
    def __init__(self, ctx: InitContext = None):
        self.ctx = ctx
        self.config = ctx.config.get_consumer().get_circuit_breaker() if ctx is not None else None
        self.plugin_config = PluginConfig()
        self.enabled = self.config is None or (self.config.is_enable() and self.config.is_default_rule_enable())
        if self.config is not None:
            interval_seconds = self.config.get_default_interval() // 1000
            if interval_seconds == 0:
                interval_seconds = config.DefaultOptions.DefaultMetricStatWindow // 1000
            sleep_seconds = self.config.get_sleep_window() // 1000
            self.plugin_config = PluginConfig(
                continuous_err_threshold=self.config.get_default_error_count(),
                metric_stat_time_window=interval_seconds * 1000,
                sleep_window=sleep_seconds * 1000 if sleep_seconds > 0 else self.config.get_sleep_window(),
                request_count_after_halfopen=self.config.get_success_count_after_half_open(),
                success_count_after_halfopen=self.config.get_success_count_after_half_open(),
                err_rate_threshold=self.config.get_default_error_percent() / 100,
                err_rate_request_threshold=self.config.get_default_minimum_request(),
            )

        if ctx is not None:
            ctx.plugins.register_event_handle(EventType.ON_LOCALVALUE_CREATED, self)

    @staticmethod
    def now():
        return int(time.time() * 1000)

    def _metrics(self, local_value):
        if local_value.circuit_breaker_metrics is None:
            metrics = InstanceMetrics(self.plugin_config)
            local_value.circuit_breaker_metrics = metrics
            local_value.set_sliding_window(metrics.window)
        return local_value.circuit_breaker_metrics

    def realtime_circuit_break(self, instance: Instance, ret: int, cost: int) -> bool:
        if not self.enabled:
            return False
        success = ret != -1 and not 500 <= ret <= 599
        status = instance.get_circuit_breaker_status()
        if status.get_status() == CBStatusEnum.HalfOpen:
            status.report_half_open_result(success)
            return (self.halfopen2open(instance, self.now()) or
                    self.halfopen2close(instance, self.now()))

        metrics = self._metrics(instance.get_local_value())
        now = self.now()

        if not metrics.error_rate_suspended:
            def callback(bucket: Bucket, value):
                if success:
                    bucket.success += value
                else:
                    bucket.total_failed += value

            metrics.window.add(1, callback, now=now)
            if not success and metrics.error_rate_check_at is None:
                metrics.error_rate_check_at = now + self.plugin_config.metric_stat_time_window

        if not metrics.consecutive_suspended:
            if success:
                metrics.consecutive_errors = 0
            else:
                metrics.consecutive_errors += 1
                if metrics.consecutive_errors == self.plugin_config.continuous_error_threshold:
                    metrics.consecutive_suspended = True
                    metrics.consecutive_errors = 0
                    if status.get_status() == CBStatusEnum.Open:
                        # The state change handler ignores close-to-open here.
                        return False
                    metrics.consecutive_triggered = True
                    return True
        return False

    def timing_circuit_break(self, instance_list: List[Instance]) -> CircuitBreakResult:
        now = self.now()
        result = CircuitBreakResult(ts=now)
        if not self.enabled:
            return result
        for instance in instance_list:
            if self.close2Open(instance, now):
                logger.warning("open circuit break for %s:%d", instance.get_host(), instance.get_port())
                result.instance_2_open.append(instance)
                continue
            elif self.open2halfopen(instance, now):
                logger.warning("half open circuit break for %s:%d", instance.get_host(), instance.get_port())
                result.instance_2_halfopen.append(instance)
                continue
            elif self.halfopen2open(instance, now):
                logger.warning("open circuit break after half open for %s:%d", instance.get_host(), instance.get_port())
                result.instance_2_open.append(instance)
                continue
            elif self.halfopen2close(instance, now):
                logger.warning("close circuit break after half open for %s:%d", instance.get_host(),
                               instance.get_port())
                result.instance_2_close.append(instance)
                continue

        return result

    def close2Open(self, instance: Instance, now: int) -> bool:
        status = instance.get_circuit_breaker_status().status
        if status == CBStatusEnum.Open:
            metrics = instance.get_local_value().circuit_breaker_metrics
            if metrics is not None:
                self._consume_due_error_rate_check(metrics, now)
            return False
        if status != CBStatusEnum.Closed:
            return False

        metrics = instance.get_local_value().circuit_breaker_metrics
        if metrics is None:
            return False
        if metrics.consecutive_triggered:
            return True
        if metrics.error_rate_check_at is None or now < metrics.error_rate_check_at:
            return False
        metrics.error_rate_check_at = None
        if self._error_rate_reaches_threshold(metrics, now):
            metrics.error_rate_suspended = True
            return True
        return False

    def _error_rate_reaches_threshold(self, metrics, now: int) -> bool:
        total_success, total_failed, _ = metrics.window.calc_interval_values(
            now - self.plugin_config.metric_stat_time_window, now)
        total_request = total_failed + total_success
        if total_request < self.plugin_config.err_rate_request_threshold:
            return False
        return total_failed / total_request >= self.plugin_config.err_rate_threshold

    def _consume_due_error_rate_check(self, metrics, now: int):
        if metrics.error_rate_check_at is None or now < metrics.error_rate_check_at:
            return
        metrics.error_rate_check_at = None
        if self._error_rate_reaches_threshold(metrics, now):
            metrics.error_rate_suspended = True

    def open2halfopen(self, instance: Instance, now: int) -> bool:
        cb_status = instance.get_circuit_breaker_status()
        if cb_status.status != CBStatusEnum.Open:
            return False

        if now - cb_status.ts < self.plugin_config.sleep_window:
            return False
        metrics = instance.get_local_value().circuit_breaker_metrics
        if metrics is not None:
            self._consume_due_error_rate_check(metrics, now)
        return True

    def halfopen2open(self, instance: Instance, now: int) -> bool:
        cb_status = instance.get_circuit_breaker_status()
        if cb_status.status != CBStatusEnum.HalfOpen:
            return False
        return cb_status.failed_requests_after_half_open > 0

    def halfopen2close(self, instance: Instance, now: int) -> bool:
        cb_status = instance.get_circuit_breaker_status()
        if cb_status.status != CBStatusEnum.HalfOpen:
            return False
        return (cb_status.failed_requests_after_half_open == 0 and
                cb_status.successful_requests_after_half_open >= self.plugin_config.success_count_after_halfopen)

    def next_check_time(self, instance: Instance):
        if not self.enabled:
            return None
        status = instance.get_circuit_breaker_status()
        if status.get_status() == CBStatusEnum.Open:
            due = status.ts + self.plugin_config.sleep_window
            metrics = instance.get_local_value().circuit_breaker_metrics
            if metrics is not None and metrics.error_rate_check_at is not None:
                due = min(due, metrics.error_rate_check_at)
            return due
        metrics = instance.get_local_value().circuit_breaker_metrics
        if status.get_status() == CBStatusEnum.Closed and metrics is not None:
            return metrics.error_rate_check_at
        return None

    def on_state_change(self, instance: Instance):
        metrics = instance.get_local_value().circuit_breaker_metrics
        if metrics is None:
            return
        status = instance.get_circuit_breaker_status().get_status()
        if status == CBStatusEnum.Open:
            metrics.consecutive_triggered = False
        elif status == CBStatusEnum.Closed:
            metrics.consecutive_suspended = False
            metrics.error_rate_suspended = False

    def get_half_open_request_count(self):
        return self.plugin_config.request_count_after_halfopen

    def on_plugin_event(self, event_type, params):
        # Counters are created lazily on the first report, matching Java.
        return

