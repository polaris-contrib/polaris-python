"""Public instance model and protobuf conversion helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from google.protobuf.wrappers_pb2 import BoolValue, StringValue, UInt32Value
from polarismesh_specification.api.v1 import model as model_api
from polarismesh_specification.api.v1.service_manage import service_pb2


RESOURCE_TYPE_METADATA = "polaris.resource.type"
PROTOCOL_METADATA = "polaris.protocol"
VERSION_METADATA = "polaris.version"


def _wrapper(message: Any, name: str, default: Any = "") -> Any:
    """Read a scalar value from a protobuf wrapper field."""
    try:
        if not message.HasField(name):
            return default
    except ValueError:
        # Proto3 scalar fields do not have presence; generated wrappers do.
        pass
    value = getattr(message, name)
    return getattr(value, "value", default)


@dataclass(slots=True)
class ServiceInstance:
    """A service instance exposed by the registration and discovery APIs."""

    service: str
    host: str
    port: int
    namespace: str = ""
    id: str = ""
    protocol: str = ""
    version: str = ""
    resource_type: str = ""
    region: str = ""
    zone: str = ""
    campus: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    healthy: bool = True
    isolate: bool = False
    weight: int = 100
    priority: int = 0
    enable_health_check: bool = True
    ttl_seconds: int | None = None

    def __post_init__(self) -> None:
        """Validate values that would otherwise produce an invalid RPC."""
        if not self.service.strip():
            raise ValueError("service must not be empty")
        if not self.host.strip():
            raise ValueError("host must not be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.weight < 0 or self.priority < 0:
            raise ValueError("weight and priority must not be negative")
        if self.ttl_seconds is not None and self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        self.metadata = {str(key): str(value) for key, value in self.metadata.items()}

    def to_proto(self, namespace: str = "") -> service_pb2.Instance:
        """Convert this instance to the generated specification message."""
        effective_namespace = self.namespace or namespace
        metadata = dict(self.metadata)
        if self.resource_type:
            metadata.setdefault(RESOURCE_TYPE_METADATA, self.resource_type)
        if self.protocol:
            metadata.setdefault(PROTOCOL_METADATA, self.protocol)
        if self.version:
            metadata.setdefault(VERSION_METADATA, self.version)
        instance = service_pb2.Instance(
            id=StringValue(value=self.id),
            service=StringValue(value=self.service),
            namespace=StringValue(value=effective_namespace),
            host=StringValue(value=self.host),
            port=UInt32Value(value=self.port),
            protocol=StringValue(value=self.protocol),
            version=StringValue(value=self.version),
            priority=UInt32Value(value=self.priority),
            weight=UInt32Value(value=self.weight),
            enable_health_check=BoolValue(value=self.enable_health_check),
            healthy=BoolValue(value=self.healthy),
            isolate=BoolValue(value=self.isolate),
            metadata=metadata,
        )
        if self.ttl_seconds is not None:
            instance.health_check.type = service_pb2.HealthCheck.HEARTBEAT
            instance.health_check.heartbeat.ttl.value = self.ttl_seconds
        if self.region or self.zone or self.campus:
            instance.location.CopyFrom(
                model_api.model_pb2.Location(
                    region=StringValue(value=self.region),
                    zone=StringValue(value=self.zone),
                    campus=StringValue(value=self.campus),
                )
            )
        return instance

    @classmethod
    def from_proto(cls, instance: service_pb2.Instance) -> ServiceInstance:
        """Build a public instance model from a generated message."""
        return cls(
            id=_wrapper(instance, "id"),
            service=_wrapper(instance, "service"),
            namespace=_wrapper(instance, "namespace"),
            host=_wrapper(instance, "host"),
            port=int(_wrapper(instance, "port", 0)),
            protocol=_wrapper(instance, "protocol"),
            version=_wrapper(instance, "version"),
            resource_type=dict(instance.metadata).get(RESOURCE_TYPE_METADATA, ""),
            region=_wrapper(instance.location, "region") if instance.HasField("location") else "",
            zone=_wrapper(instance.location, "zone") if instance.HasField("location") else "",
            campus=_wrapper(instance.location, "campus") if instance.HasField("location") else "",
            metadata=dict(instance.metadata),
            healthy=bool(_wrapper(instance, "healthy", True)),
            isolate=bool(_wrapper(instance, "isolate", False)),
            weight=int(_wrapper(instance, "weight", 100)),
            priority=int(_wrapper(instance, "priority", 0)),
            enable_health_check=bool(_wrapper(instance, "enable_health_check", True)),
            ttl_seconds=(
                int(instance.health_check.heartbeat.ttl.value)
                if instance.HasField("health_check") and instance.health_check.HasField("heartbeat")
                else None
            ),
        )


def coerce_instance(value: ServiceInstance | service_pb2.Instance | Mapping[str, Any], namespace: str = "") -> service_pb2.Instance:
    """Convert public or mapping input into a validated protobuf instance."""
    if isinstance(value, service_pb2.Instance):
        instance = service_pb2.Instance()
        instance.CopyFrom(value)
        if not instance.namespace.value and namespace:
            instance.namespace.value = namespace
        return instance
    if isinstance(value, ServiceInstance):
        return value.to_proto(namespace)
    if isinstance(value, Mapping):
        values = dict(value)
        return ServiceInstance(**values).to_proto(namespace)
    raise TypeError("instance must be ServiceInstance, protobuf Instance, or a mapping")


Instance = ServiceInstance
