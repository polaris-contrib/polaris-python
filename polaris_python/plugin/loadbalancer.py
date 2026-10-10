"""Deterministic priority and weighted instance selection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from polaris_python.core.instance import ServiceInstance


class WeightedLoadBalancer:
    """Select instances by lowest priority and proportional weight."""

    def __init__(self) -> None:
        self._counters: defaultdict[str, int] = defaultdict(int)

    def choose(self, instances: Sequence[ServiceInstance], *, key: str = "") -> ServiceInstance:
        """Choose one instance deterministically from an eligible sequence."""
        if not instances:
            raise ValueError("cannot choose from an empty instance list")
        priority = min(instance.priority for instance in instances)
        eligible = [instance for instance in instances if instance.priority == priority]
        total_weight = sum(max(instance.weight, 0) for instance in eligible)
        if total_weight <= 0:
            return eligible[self._next(key, len(eligible))]
        offset = self._next(key, total_weight)
        for instance in eligible:
            offset -= max(instance.weight, 0)
            if offset < 0:
                return instance
        return eligible[-1]

    def _next(self, key: str, size: int) -> int:
        current = self._counters[key]
        self._counters[key] = current + 1
        return current % size


LoadBalancer = WeightedLoadBalancer

