"""Metadata, priority and weight based routing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from polarismesh_specification.api.v1.model import model_pb2
from polarismesh_specification.api.v1.traffic_manage import routing_pb2

from polaris_python.core.instance import ServiceInstance


_ROUTING_POLICY = {
    value.name: value.number
    for value in routing_pb2.RouteRule.DESCRIPTOR.fields_by_name["routing_policy"].enum_type.values
}
_SOURCE_MATCH = {
    value.name: value.number
    for value in routing_pb2.SourceMatch.DESCRIPTOR.fields_by_name["type"].enum_type.values
}
_MATCH_TYPE = {
    value.name: value.number
    for value in model_pb2.MatchString.DESCRIPTOR.enum_types_by_name["MatchStringType"].values
}
# Label keys the server uses when it converts v2 rule arguments into v1
# source metadata, e.g. a QUERY argument ``env`` becomes ``$query.env``.
_LABEL_PREFIXES = (
    ("$header.", "HEADER"),
    ("$query.", "QUERY"),
    ("$cookie.", "COOKIE"),
    ("$caller_metadata.", "CALLER_METADATA"),
)
_LABEL_KEYS = {"$method": "METHOD", "$caller_ip": "CALLER_IP", "$path": "PATH"}


@dataclass(frozen=True, slots=True)
class RoutingContext:
    """Request attributes used when evaluating routing rules."""

    metadata: Mapping[str, str] = field(default_factory=dict)
    method: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, str] = field(default_factory=dict)
    caller_ip: str = ""


@dataclass(frozen=True, slots=True)
class RouteDestination:
    """A destination subset selected by a route rule."""

    metadata: Mapping[str, str] = field(default_factory=dict)
    service: str | None = None
    namespace: str | None = None
    priority: int = 0
    weight: int = 100
    isolate: bool = False

    def matches(self, instance: ServiceInstance) -> bool:
        """Return whether an instance belongs to this destination subset."""
        if self.service and instance.service != self.service:
            return False
        if self.namespace and instance.namespace != self.namespace:
            return False
        if any(instance.metadata.get(key) != value for key, value in self.metadata.items()):
            return False
        return self.isolate or not instance.isolate


@dataclass(frozen=True, slots=True)
class RouteRule:
    """A source metadata predicate and its destination subsets."""

    source_metadata: Mapping[str, str] = field(default_factory=dict)
    destinations: tuple[RouteDestination, ...] = ()
    priority: int = 0
    enabled: bool = True
    method: str | None = None
    source_arguments: tuple[tuple[int, str, str, int], ...] = ()
    nearby_match_level: int | None = None
    nearby_max_match_level: int | None = None

    def matches(self, context: RoutingContext) -> bool:
        """Return whether this rule applies to a request context."""
        if not self.enabled or (self.method and self.method != context.method):
            return False
        if any(context.metadata.get(key) != value for key, value in self.source_metadata.items()):
            return False
        return all(_argument_matches(argument, context) for argument in self.source_arguments)


class MetadataRouter:
    """Route instances using ordered source predicates and destination labels."""

    def __init__(self, rules: Iterable[RouteRule] = ()) -> None:
        self._rules: list[RouteRule] = list(rules)
        self._nearby: dict[str, RouteRule] = {}

    @property
    def rules(self) -> tuple[RouteRule, ...]:
        """Return the currently active rules."""
        return tuple(self._rules)

    def set_rules(self, rules: Iterable[RouteRule]) -> None:
        """Replace the local routing rules."""
        self._rules = sorted(rules, key=lambda item: item.priority, reverse=True)

    def add_rule(self, rule: RouteRule) -> None:
        """Add one routing rule."""
        self.set_rules([*self._rules, rule])

    def route(
        self,
        instances: Iterable[ServiceInstance],
        *,
        context: RoutingContext | None = None,
    ) -> list[ServiceInstance]:
        """Apply the first matching rule route, then the callee's nearby rule."""
        candidates = list(instances)
        context = context or RoutingContext()
        matched = next((rule for rule in self._rules if rule.matches(context)), None)
        if matched is not None and matched.nearby_match_level is not None:
            return _route_nearby(candidates, context, matched)
        if matched is not None and matched.destinations:
            candidates = self._select_destinations(candidates, matched)
        nearby = self._nearby.get(_service_key(candidates[0])) if candidates else None
        if nearby is not None:
            candidates = _route_nearby(candidates, context, nearby)
        return candidates

    def update_nearby_rules(self, namespace: str, service: str, rules: Iterable[routing_pb2.RouteRule]) -> None:
        """Replace the nearby rule delivered by ``NEARBY_ROUTE_RULE`` for one service."""
        imported = [
            rule
            for route_rule in rules
            for rule in _rules_from_route_rule(route_rule)
            if rule.nearby_match_level is not None
        ]
        key = f"{namespace}/{service}"
        if imported:
            self._nearby[key] = imported[0]
        else:
            self._nearby.pop(key, None)

    @staticmethod
    def _select_destinations(candidates: list[ServiceInstance], matched: RouteRule) -> list[ServiceInstance]:
        selected: list[ServiceInstance] = []
        destinations = sorted(matched.destinations, key=lambda item: item.priority)
        for destination in destinations:
            selected.extend(instance for instance in candidates if destination.matches(instance))
        result: list[ServiceInstance] = []
        seen: set[tuple[str, str, str, int]] = set()
        for instance in selected:
            identity = (instance.namespace, instance.service, instance.id, instance.port)
            if identity not in seen:
                seen.add(identity)
                result.append(instance)
        return result

    def update_from_proto(self, routing: routing_pb2.Routing) -> None:
        """Import metadata routing information from the specification message."""
        imported: list[RouteRule] = []
        for route in [*routing.inbounds, *routing.outbounds]:
            destinations = tuple(
                RouteDestination(
                    metadata={key: _match_value(value) for key, value in destination.metadata.items()},
                    service=_wrapper_value(destination.service),
                    namespace=_wrapper_value(destination.namespace),
                    priority=_wrapper_value(destination.priority, 0),
                    weight=_wrapper_value(destination.weight, 100),
                    isolate=_wrapper_value(destination.isolate, False),
                )
                for destination in route.destinations
            )
            for source in route.sources or [None]:
                arguments = _source_arguments(source.metadata) if source is not None else ()
                imported.append(RouteRule(destinations=destinations, priority=0, source_arguments=arguments))
        for route_rule in routing.rules:
            imported.extend(_rules_from_route_rule(route_rule))
        self.set_rules(imported)


def _rules_from_route_rule(route_rule: routing_pb2.RouteRule) -> list[RouteRule]:
    """Convert a server-delivered rule-routing or nearby rule to local form."""
    if not route_rule.enable or not route_rule.HasField("routing_config"):
        return []
    config = routing_pb2.RuleRoutingConfig()
    if route_rule.routing_policy == _ROUTING_POLICY["NearbyPolicy"]:
        nearby = routing_pb2.NearbyRoutingConfig()
        if route_rule.routing_config.Unpack(nearby):
            return [
                RouteRule(
                    priority=int(route_rule.priority),
                    nearby_match_level=int(nearby.match_level),
                    nearby_max_match_level=int(nearby.max_match_level),
                )
            ]
        return []
    if route_rule.routing_policy != _ROUTING_POLICY["RulePolicy"]:
        return []
    if not route_rule.routing_config.Unpack(config):
        return []
    groups = list(config.rules)
    if not groups:
        groups = [None]
    imported: list[RouteRule] = []
    for group in groups:
        sources = list(group.sources) if group is not None and group.sources else list(config.sources)
        destinations = list(group.destinations) if group is not None and group.destinations else list(config.destinations)
        imported.append(
            RouteRule(
                priority=int(route_rule.priority),
                enabled=route_rule.enable,
                source_arguments=tuple(
                    (int(argument.type), argument.key, _match_value(argument.value), int(argument.value.type))
                    for source in sources
                    for argument in source.arguments
                ),
                destinations=tuple(
                    RouteDestination(
                        service=_wrapper_value(destination.service),
                        namespace=_wrapper_value(destination.namespace),
                        metadata={key: _match_value(value) for key, value in destination.labels.items()},
                        priority=int(destination.priority),
                        weight=int(destination.weight),
                        isolate=bool(destination.isolate),
                    )
                    for destination in destinations
                ),
            )
        )
    return imported


def _source_arguments(metadata: Mapping[str, model_pb2.MatchString]) -> tuple[tuple[int, str, str, int], ...]:
    """Translate v1 source labels such as ``$query.env`` into rule arguments."""
    arguments: list[tuple[int, str, str, int]] = []
    for label, value in metadata.items():
        argument_type, key = _SOURCE_MATCH["CUSTOM"], label
        if label.lower() in _LABEL_KEYS:
            argument_type, key = _SOURCE_MATCH[_LABEL_KEYS[label.lower()]], ""
        else:
            for prefix, name in _LABEL_PREFIXES:
                if label.startswith(prefix):
                    argument_type, key = _SOURCE_MATCH[name], label[len(prefix):]
                    break
        arguments.append((argument_type, key, _match_value(value), int(value.type)))
    return tuple(arguments)


def _argument_matches(argument: tuple[int, str, str, int], context: RoutingContext) -> bool:
    """Evaluate a server rule source argument against the request context."""
    argument_type, key, expected, match_type = argument
    values: Mapping[str, str]
    if argument_type == _SOURCE_MATCH["METHOD"]:
        values = {"": context.method}
        key = ""
    elif argument_type == _SOURCE_MATCH["HEADER"]:
        values = {name.lower(): value for name, value in context.headers.items()}
        key = key.lower()
    elif argument_type == _SOURCE_MATCH["QUERY"]:
        values = context.query
    elif argument_type == _SOURCE_MATCH["CALLER_IP"]:
        values = {"": context.caller_ip}
        key = ""
    elif argument_type in {_SOURCE_MATCH["CALLER_METADATA"], _SOURCE_MATCH["CUSTOM"]}:
        values = context.metadata
    else:
        return False
    actual = values.get(key)
    if actual is None:
        return False
    if match_type == _MATCH_TYPE["REGEX"]:
        return re.fullmatch(expected, actual) is not None
    if match_type == _MATCH_TYPE["NOT_EQUALS"]:
        return actual != expected
    if match_type in {_MATCH_TYPE["IN"], _MATCH_TYPE["NOT_IN"]}:
        choices = {item.strip() for item in expected.split(",")}
        matched = actual in choices
        return not matched if match_type == _MATCH_TYPE["NOT_IN"] else matched
    return actual == expected


def _route_nearby(
    instances: list[ServiceInstance], context: RoutingContext, rule: RouteRule
) -> list[ServiceInstance]:
    """Select the nearest instances using region/zone/campus labels."""
    location = context.metadata
    levels = ((1, "campus"), (2, "zone"), (3, "region"))
    start = rule.nearby_match_level or 1
    maximum = rule.nearby_max_match_level or 3
    if start == 4:
        start = 1
    if maximum == 4:
        maximum = 3
    for level, key in levels:
        if not start <= level <= maximum or not location.get(key):
            continue
        selected = [
            instance
            for instance in instances
            if _instance_location(instance, key) == location.get(key)
        ]
        if selected:
            return selected
    return instances


def _service_key(instance: ServiceInstance) -> str:
    return f"{instance.namespace}/{instance.service}"


def _instance_location(instance: ServiceInstance, key: str) -> str:
    """Read a location field, accepting metadata for older registrations."""
    value = getattr(instance, key, "")
    return value or instance.metadata.get(key, "")


def _wrapper_value(value: object, default: object = "") -> object:
    """Read a protobuf wrapper without treating an unset value as meaningful."""
    return getattr(value, "value", default)


def _match_value(value: model_pb2.MatchString) -> str:
    """Extract an exact-match value from a specification matcher."""
    return _wrapper_value(value.value, "")  # type: ignore[return-value]


Router = MetadataRouter

