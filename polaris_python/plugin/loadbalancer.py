"""Deterministic priority and weighted instance selection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from threading import Lock

from polaris_python.core.instance import ServiceInstance


class WeightedLoadBalancer:
    """Select instances by lowest priority, then smooth weighted round robin."""

    def __init__(self) -> None:
        self._current: defaultdict[str, dict[tuple[str, str, str, str, int], int]] = defaultdict(dict)
        self._lock = Lock()

    def choose(self, instances: Sequence[ServiceInstance], *, key: str = "") -> ServiceInstance:
        """Choose one instance deterministically from an eligible sequence."""
        if not instances:
            raise ValueError("cannot choose from an empty instance list")
        priority = min(instance.priority for instance in instances)
        eligible = [instance for instance in instances if instance.priority == priority]
        weights = [max(instance.weight, 0) for instance in eligible]
        if sum(weights) <= 0:
            weights = [1] * len(eligible)
        total = sum(weights)
        identities = [_identity(instance) for instance in eligible]
        with self._lock:
            current = self._current[key]
            for stale in set(current) - set(identities):
                del current[stale]
            best = 0
            for index, (identity, weight) in enumerate(zip(identities, weights)):
                current[identity] = current.get(identity, 0) + weight
                if current[identity] > current[identities[best]]:
                    best = index
            current[identities[best]] -= total
        return eligible[best]


def _identity(instance: ServiceInstance) -> tuple[str, str, str, str, int]:
    return (instance.namespace, instance.service, instance.id, instance.host, instance.port)


LoadBalancer = WeightedLoadBalancer
