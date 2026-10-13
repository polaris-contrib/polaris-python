"""Server connector abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from polarismesh_specification.api.v1.service_manage import client_pb2, request_pb2, response_pb2, service_pb2


class ServerConnector(ABC):
    """Server transport.

    The gRPC implementation follows polaris-java ``connector-polaris-grpc``
    (``GrpcConnector``, ``ConnectionManager``, ``SpecStreamClient``).
    """

    @abstractmethod
    async def register_instance(self, instance: service_pb2.Instance) -> response_pb2.Response:
        """Register an instance."""

    @abstractmethod
    async def deregister_instance(self, instance: service_pb2.Instance) -> response_pb2.Response:
        """Deregister an instance."""

    @abstractmethod
    async def heartbeat(self, instance: service_pb2.Instance) -> response_pb2.Response:
        """Send an instance heartbeat."""

    @abstractmethod
    async def report_client(self, client: client_pb2.Client) -> response_pb2.Response:
        """Report this SDK client; the response carries the location Polaris resolved for it."""

    @abstractmethod
    def discover(self, request: request_pb2.DiscoverRequest) -> AsyncIterator[response_pb2.DiscoverResponse]:
        """Open a long-lived instance discovery stream."""

    @abstractmethod
    async def close(self) -> None:
        """Close network resources."""
