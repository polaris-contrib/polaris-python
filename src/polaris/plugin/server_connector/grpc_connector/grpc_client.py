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

"""Server connector plugin backed by the Polaris gRPC API."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from collections.abc import AsyncIterator

from polarismesh_specification.api.v1.service_manage import response_pb2

from polaris.pkg.model.error import ErrorCode, SDKError, ServerCode, ensure_response
from polaris.pkg.model.server import (
    InstanceDeRegisterRequest,
    InstanceDiscoverRequest,
    InstanceHeartbeatRequest,
    InstanceRegisterRequest,
    InstanceRegisterResponse,
    ReportClientRequest,
    ReportClientResponse,
)
from polaris.pkg.model.service import GetOneInstanceRequest, InstancesResponse
from ..base import BaseServerConnector
from ..convert import (
    contract_request_to_proto,
    contract_response_from_proto,
    deregister_request_to_proto,
    discover_request_to_proto,
    heartbeat_request_to_proto,
    register_request_to_proto,
    report_client_to_proto,
)
from polaris.plugin_manager import InitContext, PluginType, register_plugin

from .connection import GrpcConnection, GrpcSettings
from .tls import channel_credentials


@register_plugin(PluginType.SERVER_CONNECTOR, "grpc")
class GrpcConnector(BaseServerConnector):
    """Adapt internal SDK request objects to specification gRPC calls."""

    def __init__(self, init_ctx: InitContext) -> None:
        self.init_ctx = init_ctx
        self.config = init_ctx.config
        connector_config = self.config.get_global().get_server_connector()
        api_config = self.config.get_global().get_api()
        cache_config = self.config.get_consumer().get_local_cache()
        self.connection = GrpcConnection(
            GrpcSettings(
                addresses=connector_config.get_addresses(),
                timeout_seconds=max(connector_config.get_message_timeout(), 1) / 1000,
                token=connector_config.get_token(),
                retry_attempts=api_config.get_max_retry_times(),
                retry_backoff_seconds=max(api_config.get_retry_interval(), 0) / 1000,
                refresh_interval_seconds=max(cache_config.get_service_refresh_interval(), 1) / 1000,
                switch_interval_seconds=max(connector_config.get_server_switch_interval(), 1) / 1000,
                credentials=channel_credentials(connector_config),
            ),
            context_logger=init_ctx.logger,
        )
        self._streams: dict[str, AsyncIterator[response_pb2.DiscoverResponse]] = {}
        self._stream_locks: dict[str, asyncio.Lock] = {}
        self._closed = False
        self.engine = None
        self._cluster_connections = {}
        self._stream_connections = {}

    def start_address_switching(self):
        """Start Java-compatible periodic rotation for the bootstrap connection."""
        self._start_address_switching(self.connection, self.engine.loop if self.engine is not None else None)

    def _start_address_switching(self, connection, loop=None):
        connection.on_switch = lambda: self._on_address_switched(connection)
        connection.start_switching(loop)

    async def _on_address_switched(self, connection):
        """Close streams pinned to the old endpoint so the next read reconnects."""
        keys = [key for key, owner in self._stream_connections.items() if owner is connection]
        for key in keys:
            stream = self._streams.get(key)
            if stream is None:
                self._stream_connections.pop(key, None)
                continue
            lock = self._stream_locks.get(key)
            if lock is not None and not lock.locked():
                async with lock:
                    if self._streams.get(key) is stream:
                        self._streams.pop(key, None)
                        self._stream_connections.pop(key, None)
                    await stream.aclose()
            else:
                await stream.aclose()
                self._streams.pop(key, None)
                self._stream_connections.pop(key, None)

    async def _connection(self, heartbeat=False):
        system = self.config.get_global().get_system()
        cluster = system.get_health_check_cluster() if heartbeat else system.get_discover_cluster()
        if not cluster.namespace or not cluster.service or self.engine is None:
            return self.connection
        key = (cluster.namespace, cluster.service)
        from polaris.pkg.model.service import GetInstancesRequest
        snapshot = await self.engine._query_instances(GetInstancesRequest(
            namespace=cluster.namespace, service=cluster.service), "healthy")
        if snapshot is None or not snapshot.instances:
            raise SDKError(ErrorCode.ErrCodeAPIInstanceNotFound, f"No system service instance for {key}")
        addresses = []
        for node in snapshot.instances:
            host = node.get_host()
            addresses.append(f"[{host}]:{node.get_port()}" if ":" in host else f"{host}:{node.get_port()}")
        if key not in self._cluster_connections:
            connection = GrpcConnection(replace(self.connection.settings, addresses=addresses),
                                        context_logger=self.init_ctx.logger)
            connection.target_service = key
            connection.stat_reporter = self.connection.stat_reporter
            connection.address_resolver = lambda: self._connection(heartbeat=heartbeat)
            self._cluster_connections[key] = connection
        connection = self._cluster_connections[key]
        self._start_address_switching(connection)
        connection._addresses = addresses
        return connection

    async def register_instance(self, request: InstanceRegisterRequest) -> InstanceRegisterResponse:
        connection = await self._connection()
        response = await connection.register_instance(
            register_request_to_proto(request), auto_heartbeat=request.auto_heartbeat,
        )
        ensure_response(response, (ServerCode.ExecuteSuccess, ServerCode.ExistedResource))
        instance_id = response.instance.id.value if response.HasField("instance") else ""
        return InstanceRegisterResponse(instance_id)

    async def deregister_instance(self, request: InstanceDeRegisterRequest) -> None:
        connection = await self._connection()
        response = await connection.deregister_instance(deregister_request_to_proto(request))
        ensure_response(response, (ServerCode.ExecuteSuccess, ServerCode.NotFoundResource))

    @staticmethod
    def _stream_key(request: InstanceDiscoverRequest) -> str:
        return f"{request.namespace}\\x00{request.name}\\x00{request.type}"

    async def discover(
        self,
        request: InstanceDiscoverRequest,
        use_discover_cache: bool = True,
    ) -> response_pb2.DiscoverResponse:
        del use_discover_cache
        if self._closed:
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "gRPC connector has been closed")
        key = self._stream_key(request)
        lock = self._stream_locks.setdefault(key, asyncio.Lock())
        async with lock:
            stream = self._streams.get(key)
            if stream is None:
                system = self.config.get_global().get_system()
                system_keys = {(system.get_discover_cluster().namespace, system.get_discover_cluster().service),
                               (system.get_health_check_cluster().namespace, system.get_health_check_cluster().service)}
                connection = (self.connection if (request.namespace, request.name) in system_keys
                              else await self._connection())
                stream = connection.discover(discover_request_to_proto(request))
                self._streams[key] = stream
                self._stream_connections[key] = connection
            try:
                response = await anext(stream)
            except StopAsyncIteration:
                self._streams.pop(key, None)
                self._stream_connections.pop(key, None)
                raise SDKError(ErrorCode.ErrCodeNetworkError, f"Discover stream closed for {request.name}")
            except (asyncio.CancelledError, Exception):
                self._streams.pop(key, None)
                self._stream_connections.pop(key, None)
                await stream.aclose()
                raise
        ensure_response(response)
        return response

    async def stop_discover(self, request: InstanceDiscoverRequest) -> None:
        """Close one idle resource stream without closing shared gRPC channels."""
        key = self._stream_key(request)
        lock = self._stream_locks.get(key)
        if lock is None:
            return
        async with lock:
            stream = self._streams.pop(key, None)
            self._stream_connections.pop(key, None)
            try:
                if stream is not None:
                    await stream.aclose()
            finally:
                self._stream_locks.pop(key, None)

    async def heartbeat(self, request: InstanceHeartbeatRequest) -> None:
        connection = await self._connection(heartbeat=True)
        response = await connection.heartbeat(heartbeat_request_to_proto(request))
        ensure_response(response)

    async def report_client(self, request: ReportClientRequest) -> ReportClientResponse:
        connection = await self._connection()
        response = await connection.report_client(report_client_to_proto(request))
        ensure_response(response)
        if not response.HasField("client") or not response.client.HasField("location"):
            return ReportClientResponse("", "", "")
        location = response.client.location
        return ReportClientResponse(location.region.value, location.zone.value, location.campus.value)

    async def report_service_contract(self, request):
        """Report the contract over the discovery connection's channel."""
        connection = await self._connection()
        response = await connection._unary(
            "ReportServiceContract", contract_request_to_proto(request),
            timeout_seconds=request.timeout / 1000 if request.timeout else None,
        )
        ensure_response(response)

    async def get_service_contract(self, request):
        """Retrieve a contract without adding another discovery cache type."""
        connection = await self._connection()
        response = await connection._unary(
            "GetServiceContract", contract_request_to_proto(request),
            timeout_seconds=request.timeout / 1000 if request.timeout else None,
        )
        ensure_response(response)
        if not response.HasField("serviceContract"):
            raise SDKError(ErrorCode.ErrCodeInvalidResponse, "missing service contract response")
        return contract_response_from_proto(response.serviceContract)

    def get_one_instance(self, request: GetOneInstanceRequest) -> InstancesResponse:
        del request
        raise SDKError(ErrorCode.ErrCodePluginError, "single-instance server RPC is not implemented")

    async def close(self) -> None:
        """Close discovery streams and their gRPC channels."""
        if self._closed:
            return
        self._closed = True
        streams = list(self._streams.values())
        self._streams.clear()
        self._stream_locks.clear()
        self._stream_connections.clear()
        for stream in streams:
            try:
                await stream.aclose()
            except RuntimeError:
                pass
        await self.connection.close()
        for connection in self._cluster_connections.values():
            await connection.close()
        self._cluster_connections.clear()
