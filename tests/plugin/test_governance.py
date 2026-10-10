from __future__ import annotations

import asyncio

import pytest
from google.protobuf.any_pb2 import Any
from google.protobuf.wrappers_pb2 import StringValue
from polarismesh_specification.api.v1.model import model_pb2
from polarismesh_specification.api.v1.traffic_manage import routing_pb2

from polaris_python.core.error import CircuitOpenError, RateLimitExceededError
from polaris_python.core.instance import ServiceInstance
from polaris_python.plugin.circuitbreaker import CircuitBreaker, CircuitBreakerRule, CircuitState
from polaris_python.plugin.loadbalancer import WeightedLoadBalancer
from polaris_python.plugin.ratelimiter import RateLimitRule, RateLimiter
from polaris_python.plugin.router import MetadataRouter, RouteDestination, RouteRule, RoutingContext


def test_router_matches_source_metadata_and_destination_subset() -> None:
    instances = [
        ServiceInstance(service="svc", namespace="n", host="a", port=1, id="a", metadata={"version": "v1"}),
        ServiceInstance(service="svc", namespace="n", host="b", port=2, id="b", metadata={"version": "v2"}),
    ]
    router = MetadataRouter(
        [
            RouteRule(
                source_metadata={"tenant": "blue"},
                destinations=(RouteDestination(metadata={"version": "v2"}),),
                priority=10,
            )
        ]
    )

    selected = router.route(instances, context=RoutingContext(metadata={"tenant": "blue"}))
    assert [instance.id for instance in selected] == ["b"]


def test_router_imports_server_rule_routing_config() -> None:
    matcher = model_pb2.MatchString(value=StringValue(value="pre"))
    config = routing_pb2.RuleRoutingConfig(
        sources=[
            routing_pb2.SourceService(
                arguments=[routing_pb2.SourceMatch(type=2, key="env", value=matcher)]
            )
        ],
        destinations=[routing_pb2.DestinationGroup(labels={"env": matcher})],
    )
    packed = Any()
    packed.Pack(config)
    routing = routing_pb2.Routing(
        rules=[routing_pb2.RouteRule(enable=True, routing_policy=0, routing_config=packed)]
    )
    router = MetadataRouter()
    router.update_from_proto(routing)
    instances = [
        ServiceInstance(service="svc", host="a", port=1, metadata={"env": "dev"}),
        ServiceInstance(service="svc", host="b", port=2, metadata={"env": "pre"}),
    ]

    selected = router.route(instances, context=RoutingContext(headers={"Env": "pre"}))
    assert [instance.host for instance in selected] == ["b"]


def test_router_imports_server_nearby_rule() -> None:
    config = routing_pb2.NearbyRoutingConfig(match_level=1, max_match_level=3)
    packed = Any()
    packed.Pack(config)
    routing = routing_pb2.Routing(
        rules=[routing_pb2.RouteRule(enable=True, routing_policy=2, routing_config=packed)]
    )
    router = MetadataRouter()
    router.update_from_proto(routing)
    instances = [
        ServiceInstance(service="svc", host="a", port=1, region="cn", zone="gz", campus="a"),
        ServiceInstance(service="svc", host="b", port=2, region="cn", zone="gz", campus="b"),
    ]

    selected = router.route(
        instances,
        context=RoutingContext(metadata={"region": "cn", "zone": "gz", "campus": "b"}),
    )
    assert [instance.host for instance in selected] == ["b"]


def test_weighted_load_balancer_honors_priority_and_weight() -> None:
    instances = [
        ServiceInstance(service="svc", host="a", port=1, id="a", priority=1),
        ServiceInstance(service="svc", host="b", port=2, id="b", priority=0),
    ]
    assert WeightedLoadBalancer().choose(instances).id == "b"


@pytest.mark.asyncio
async def test_rate_limiter_enforces_concurrency_and_release() -> None:
    limiter = RateLimiter([RateLimitRule("svc", max_concurrency=1)])
    await limiter.acquire("svc")
    with pytest.raises(RateLimitExceededError):
        await limiter.acquire("svc")
    limiter.release("svc")
    await limiter.acquire("svc")


def test_circuit_breaker_opens_and_recovers() -> None:
    breaker = CircuitBreaker(
        [CircuitBreakerRule("svc", failure_threshold=2, recovery_timeout_seconds=0.01)]
    )
    breaker.record_failure("svc")
    breaker.record_failure("svc")
    assert breaker.state("svc") == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.check("svc")
    asyncio.run(asyncio.sleep(0.02))
    breaker.check("svc")
    breaker.record_success("svc")
    assert breaker.state("svc") == CircuitState.CLOSED
