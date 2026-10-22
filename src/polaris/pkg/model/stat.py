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
import threading
from typing import List, Tuple


class InstanceGauge:
    def get_id(self) -> str:
        pass

    def get_namespace(self) -> str:
        pass

    def get_service(self) -> str:
        pass

    def get_api(self) -> str:
        pass

    def get_host(self) -> str:
        pass

    def get_port(self) -> int:
        pass

    def get_ret_status(self) -> int:
        pass

    def get_ret_code(self) -> int:
        pass

    def get_delay(self) -> int:
        pass

    def validate(self) -> bool:
        pass


class BucketMetric:
    def __init__(self):
        self.success = 0
        self.total_failed = 0
        self.continuous_failed = 0


class Bucket:
    def __init__(self, begin_time=0, end_time=0):
        self.lock = threading.RLock()
        self.begin_time = begin_time
        self.end_time = end_time
        self.metric = BucketMetric()

    @property
    def success(self):
        return self.metric.success

    @success.setter
    def success(self, val):
        self.metric.success = val

    @property
    def total_failed(self):
        return self.metric.total_failed

    @total_failed.setter
    def total_failed(self, val):
        self.metric.total_failed = val

    @property
    def continuous_failed(self):
        return self.metric.continuous_failed

    @continuous_failed.setter
    def continuous_failed(self, val):
        self.metric.continuous_failed = val


class SlidingWindow:
    def __init__(self, bucket_count: int, bucket_interval: int):
        """

        :param bucket_count: 窗口内桶总数
        :param bucket_interval: 桶的时长(ms)
        """
        self.win_chain: List[Bucket] = []
        self.bucket_count = bucket_count
        self.bucket_interval = bucket_interval
        self.lock = threading.RLock()

    @property
    def window_length(self):
        return self.bucket_count * self.bucket_interval

    def _bucket_for(self, now: int) -> Bucket:
        tail = self.win_chain[-1] if self.win_chain else None
        if tail is not None and tail.begin_time <= now < tail.end_time:
            return tail

        # A long idle gap recreates the window; otherwise append the bucket
        # that contains the current timestamp.
        if tail is None or tail.end_time + self.window_length <= now:
            self.win_chain = [Bucket(now, now + self.bucket_interval)]
            return self.win_chain[0]

        next_start = tail.end_time + (now - tail.end_time) // self.bucket_interval
        bucket = Bucket(next_start, next_start + self.bucket_interval)
        while (self.win_chain and
               self.win_chain[0].begin_time + self.window_length <= next_start):
            self.win_chain.pop(0)
        self.win_chain.append(bucket)
        return bucket

    def add(self, value, cb, *, now=None):
        if now is None:
            now = int(time.time() * 1000)
        with self.lock:
            cur_bucket = self._bucket_for(now)
            with cur_bucket.lock:
                ret = cb(cur_bucket, value)
        return ret

    def lookup(self, cur_time: int) -> Bucket:
        with self.lock:
            return self._bucket_for(cur_time)

    def calc_interval_values(self, begin_time: int, end_time: int) -> Tuple:
        total_success = 0
        total_failed = 0
        continuous_failed = 0

        with self.lock:
            for b in self.win_chain:
                with b.lock:
                    if begin_time >= b.end_time:
                        continue
                    if end_time <= b.begin_time:
                        continue

                    total_success += b.success
                    total_failed += b.total_failed
                    continuous_failed += b.continuous_failed

        return total_success, total_failed, continuous_failed


ApiGetOneInstance = "Consumer::GetOneInstance"
ApiGetInstances = "Consumer::GetInstances"
ApiAsyncGetOneInstance = "Consumer::AsyncGetOneInstance"
ApiAsyncGetInstances = "Consumer::AsyncGetInstances"
ApiGetRouteRule = "Consumer::GetRouteRule"

ApiRegister = "Provider::Register"
ApiDeregister = "Provider::Deregister"
ApiHeartbeat = "Provider::Heartbeat"
