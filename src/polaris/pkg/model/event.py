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

"""Context-owned event center for capabilities implemented by this SDK."""

from dataclasses import dataclass, field
from threading import RLock
import time


class SDKEventType:
    """Only event categories backed by implemented runtime behavior."""

    INSTANCE = "INSTANCE"
    CIRCUIT_BREAKING = "CIRCUIT_BREAKING"


class SDKEventName:
    INSTANCE_THREAD_END = "InstanceThreadEnd"
    ON_SERVICE_ADDED = "OnServiceAdded"
    ON_SERVICE_UPDATED = "OnServiceUpdated"
    ON_SERVICE_DELETED = "OnServiceDeleted"
    CIRCUIT_BREAKER_OPEN = "CircuitBreakerOpen"
    CIRCUIT_BREAKER_HALF_OPEN = "CircuitBreakerHalfOpen"
    CIRCUIT_BREAKER_CLOSE = "CircuitBreakerClose"


class SDKEventStatus:
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    HALF_OPEN = "HALF_OPEN"


# Java EventConstants pairs this SDK can emit. Cache lifecycle names stay local.
_REMOTE_EVENT_KEYS = frozenset({
    (SDKEventType.INSTANCE, SDKEventName.INSTANCE_THREAD_END),
    (SDKEventType.CIRCUIT_BREAKING, SDKEventName.CIRCUIT_BREAKER_OPEN),
    (SDKEventType.CIRCUIT_BREAKING, SDKEventName.CIRCUIT_BREAKER_HALF_OPEN),
    (SDKEventType.CIRCUIT_BREAKING, SDKEventName.CIRCUIT_BREAKER_CLOSE),
})


def is_remote_reportable(event) -> bool:
    """Return whether Java EventReporter would accept this event type and name."""
    return (event.event_type, event.event_name) in _REMOTE_EVENT_KEYS


@dataclass(frozen=True)
class SDKEvent:
    """One immutable event emitted by an implemented SDK capability."""

    event_type: str
    event_name: str
    timestamp: int
    client_id: str
    namespace: str
    service: str
    client_ip: str = ""
    old_value: object = None
    new_value: object = None
    instance_id: str = ""
    host: str = ""
    port: int = 0
    previous_status: str = ""
    current_status: str = ""
    rule_name: str = ""
    reason: str = ""
    additional: dict = field(default_factory=dict)

    def to_log_message(self):
        """Format an event using the Java and Go logger field order."""
        identity = f"{self.instance_id}@{self.host}:{self.port}" if self.instance_id else ""
        states = f" {self.previous_status}->{self.current_status}" if self.current_status else ""
        return (f"{self.event_type}|{self.event_name}|{self.timestamp}|{self.client_id}|"
                f"{self.client_ip}|{identity}{states}|{self.namespace}|{self.service}|{self.reason}")


class EventCenter:
    """Dispatch context-local events without affecting SDK control flow."""

    def __init__(self, value_context=None):
        self.value_context = value_context
        self.logger = value_context.logger.get_logger("event") if value_context.logger is not None else None
        self._lock = RLock()
        self._listeners = []
        self.register_listener(self._log_event)

    @staticmethod
    def _listener_name(listener):
        if hasattr(listener, "__name__"):
            return listener.__name__
        return type(listener).__name__

    @staticmethod
    def _invoke(listener, event):
        method = getattr(listener, "on_sdk_event", None)
        if method is not None:
            return method(event)
        return listener(event)

    def register_listener(self, listener, event_type: str | None = None):
        """Register a callable or on_sdk_event object, optionally for one event type."""
        if not callable(listener) and not hasattr(listener, "on_sdk_event"):
            raise TypeError("event listener must be callable or implement on_sdk_event")
        with self._lock:
            self._listeners.append((listener, event_type))

    def unregister_listener(self, listener, event_type: str | None = None):
        """Remove one exact listener registration."""
        with self._lock:
            self._listeners = [(item, subscribed_type)
                               for item, subscribed_type in self._listeners
                               if item is not listener or subscribed_type != event_type]

    def publish(self, event: SDKEvent):
        """Notify matching listeners and isolate their exceptions."""
        with self._lock:
            listeners = list(self._listeners)
        for listener, event_type in listeners:
            if event_type is not None and event_type != event.event_type:
                continue
            try:
                self._invoke(listener, event)
            except Exception as error:
                if self.logger is not None:
                    self.logger.warning("event listener %s failed: %s", self._listener_name(listener), error)

    def close(self):
        """Drop listeners when the owning context is destroyed."""
        with self._lock:
            self._listeners.clear()

    def _log_event(self, event):
        if self.logger is None:
            return
        self.logger.info("%s", event.to_log_message())


def now_event(client_id: str, event_type: str, event_name: str, **values) -> SDKEvent:
    """Build a timestamped event for internal emitters."""
    return SDKEvent(event_type=event_type, event_name=event_name, timestamp=int(time.time() * 1000),
                    client_id=client_id, **values)
