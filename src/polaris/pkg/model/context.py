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

from threading import RLock
from uuid import uuid4

ContextKeyEngine = "engine"
ContextKeyEventCenter = "event_center"


class ValueContext:
    """Hold identity and thread-safe values belonging to one SDK context."""

    def __init__(self):
        self.client_id = str(uuid4())
        self.logger = None
        self.core_map = {}
        self._lock = RLock()

    def set_value(self, key: str, value):
        """Store a value without touching any other SDK context."""
        with self._lock:
            self.core_map[key] = value

    def get_value(self, key: str):
        """Read a value owned by this context."""
        with self._lock:
            return self.core_map[key]

    def get_client_id(self) -> str:
        """Return the stable, unique identity used in ReportClient."""
        return self.client_id

    def clear(self):
        """Release runtime references after context destruction."""
        with self._lock:
            self.core_map.clear()


def new_value_context():
    return ValueContext()
