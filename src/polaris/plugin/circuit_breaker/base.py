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

from abc import ABC, abstractmethod
from typing import Dict, List

from polaris.pkg.model.service import Instance

__all__ = ["BaseCircuitBreaker", "CircuitBreakResult"]


class CircuitBreakResult:
    def __init__(self, ts=None):
        self.now = ts
        self.instance_2_open = []
        self.instance_2_halfopen = []
        self.instance_2_close = []


class BaseCircuitBreaker(ABC):
    """
    熔断判断返回是否需要进行熔断
    """

    @abstractmethod
    def realtime_circuit_break(self, instance: Instance, ret: int, cost: int) -> bool:
        pass

    def timing_circuit_break(self, instance_list: List[Instance]) -> CircuitBreakResult:
        pass

    def next_check_time(self, instance: Instance):
        return None

    def now(self):
        raise NotImplementedError

    def on_state_change(self, instance: Instance):
        pass

    def get_half_open_request_count(self):
        return 3
