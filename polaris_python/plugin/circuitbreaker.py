"""Failure-based circuit breaker with closed, open and half-open states."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Iterable

from polarismesh_specification.api.v1.fault_tolerance import circuitbreaker_pb2

from polaris_python.core.error import CircuitOpenError


class CircuitState(str, Enum):
    """Circuit lifecycle states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class CircuitBreakerRule:
    """Failure and recovery policy for one service key."""

    key: str
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 30.0
    success_threshold: int = 1
    minimum_requests: int = 1
    error_rate_threshold: float | None = None
    enabled: bool = True


@dataclass(slots=True)
class _Circuit:
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    half_open_successes: int = 0
    half_open_probes: int = 0
    opened_at: float = 0.0
    samples: deque[bool] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.samples is None:
            self.samples = deque(maxlen=100)


class CircuitBreaker:
    """Guard calls and automatically probe recovery after an open interval."""

    def __init__(self, rules: Iterable[CircuitBreakerRule] = ()) -> None:
        self._rules: dict[str, CircuitBreakerRule] = {rule.key: rule for rule in rules}
        self._circuits: dict[str, _Circuit] = {}
        self._lock = RLock()

    @property
    def rules(self) -> tuple[CircuitBreakerRule, ...]:
        """Return configured circuit breaker rules."""
        return tuple(self._rules.values())

    def set_rules(self, rules: Iterable[CircuitBreakerRule]) -> None:
        """Replace local circuit policies and reset their runtime state."""
        with self._lock:
            self._rules = {rule.key: rule for rule in rules}
            self._circuits.clear()

    def state(self, key: str) -> CircuitState:
        """Return the current state for a service key."""
        with self._lock:
            return self._circuits.setdefault(key, _Circuit()).state

    def allow(self, key: str) -> bool:
        """Reserve a call slot, returning false while the circuit is open."""
        with self._lock:
            rule = self._rules.get(key) or self._rules.get("*")
            if rule is None or not rule.enabled:
                return True
            circuit = self._circuits.setdefault(key, _Circuit())
            now = time.monotonic()
            if circuit.state == CircuitState.OPEN:
                if now - circuit.opened_at < rule.recovery_timeout_seconds:
                    return False
                circuit.state = CircuitState.HALF_OPEN
                circuit.half_open_probes = 0
                circuit.half_open_successes = 0
            if circuit.state == CircuitState.HALF_OPEN:
                if circuit.half_open_probes >= 1:
                    return False
                circuit.half_open_probes += 1
            return True

    def check(self, key: str) -> None:
        """Raise ``CircuitOpenError`` when a call is not allowed."""
        if not self.allow(key):
            raise CircuitOpenError(f"circuit is open for {key}")

    def is_open(self, key: str) -> bool:
        """Return whether a key is currently blocked without reserving a probe."""
        with self._lock:
            circuit = self._circuits.setdefault(key, _Circuit())
            rule = self._rules.get(key) or self._rules.get("*")
            if (
                rule is not None
                and circuit.state == CircuitState.OPEN
                and time.monotonic() - circuit.opened_at >= rule.recovery_timeout_seconds
            ):
                return False
            return circuit.state == CircuitState.OPEN

    def record_success(self, key: str) -> None:
        """Record a successful call and close a recovered circuit."""
        with self._lock:
            rule = self._rules.get(key) or self._rules.get("*")
            if rule is None or not rule.enabled:
                return
            circuit = self._circuits.setdefault(key, _Circuit())
            circuit.samples.append(True)
            circuit.consecutive_failures = 0
            if circuit.state == CircuitState.HALF_OPEN:
                circuit.half_open_successes += 1
                if circuit.half_open_successes >= rule.success_threshold:
                    circuit.state = CircuitState.CLOSED
                    circuit.half_open_probes = 0
            
    def record_failure(self, key: str) -> None:
        """Record a failed call and open the circuit when the policy triggers."""
        with self._lock:
            rule = self._rules.get(key) or self._rules.get("*")
            if rule is None or not rule.enabled:
                return
            circuit = self._circuits.setdefault(key, _Circuit())
            circuit.samples.append(False)
            circuit.consecutive_failures += 1
            circuit.half_open_probes = 0
            error_rate = 1 - (sum(circuit.samples) / len(circuit.samples)) if circuit.samples else 0
            if (
                circuit.state == CircuitState.HALF_OPEN
                or circuit.consecutive_failures >= rule.failure_threshold
                or (
                    rule.error_rate_threshold is not None
                    and len(circuit.samples) >= rule.minimum_requests
                    and error_rate >= rule.error_rate_threshold
                )
            ):
                circuit.state = CircuitState.OPEN
                circuit.opened_at = time.monotonic()

    def record(self, key: str, *, success: bool) -> None:
        """Record a call result."""
        (self.record_success if success else self.record_failure)(key)

    def update_from_proto(self, circuit_breaker: circuitbreaker_pb2.CircuitBreaker) -> None:
        """Import service-level circuit policies from specification messages."""
        rules: list[CircuitBreakerRule] = []
        for rule in circuit_breaker.rules:
            key = f"{rule.namespace}/{rule.rule_matcher.destination.service}"
            failure_threshold = 5
            minimum_requests = 1
            error_rate_threshold = None
            for trigger in rule.trigger_condition:
                if trigger.error_count:
                    failure_threshold = trigger.error_count
                if trigger.minimum_request:
                    minimum_requests = trigger.minimum_request
                if trigger.error_percent:
                    error_rate_threshold = trigger.error_percent / 100
            recovery_timeout = float(rule.recoverCondition.sleep_window or 30)
            success_threshold = max(1, rule.recoverCondition.consecutiveSuccess or 1)
            rules.append(
                CircuitBreakerRule(
                    key,
                    failure_threshold=failure_threshold,
                    recovery_timeout_seconds=recovery_timeout,
                    success_threshold=success_threshold,
                    minimum_requests=minimum_requests,
                    error_rate_threshold=error_rate_threshold,
                    enabled=rule.enable,
                )
            )
        self.set_rules(rules)

