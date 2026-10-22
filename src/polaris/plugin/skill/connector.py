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

"""Skill RPCs using a separate specification gRPC connection."""

import asyncio

import grpc
from polarismesh_specification.api.v1.skill_manage import skill_service_pb2 as pb, skill_service_pb2_grpc

from polaris.pkg.model.error import ErrorCode, SDKError, ServerCode, ensure_response
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection, GrpcSettings, _request_id
from polaris.plugin_manager import PluginType, register_plugin
from polaris.plugin.server_connector.grpc_connector.tls import channel_credentials


@register_plugin(PluginType.SKILL_CONNECTOR, "polaris")
class SkillConnector:
    """Own the independent Skill channels and validate streamed downloads."""

    def __init__(self, init_ctx):
        self.config = init_ctx.config.get_ai().get_skill().get_server_connector()
        api = init_ctx.config.get_global().get_api()
        self.connection = GrpcConnection(
            GrpcSettings(self.config.addresses, self.config.message_timeout / 1000,
                         self.config.token, api.max_retry_times, api.retry_interval / 1000,
                         credentials=channel_credentials(self.config)),
            context_logger=init_ctx.logger, stub_factory=skill_service_pb2_grpc.PolarisSkillStub,
        )

    async def get_skill(self, request):
        """Fetch one published skill and preserve the server response code."""
        response = ensure_response(await self.connection._unary(
            "GetSkill", pb.GetSkillRequest(namespace=request.namespace, name=request.name, version=request.version),
            timeout_seconds=(request.timeout or self.config.message_timeout) / 1000,
        ), (0, ServerCode.ExecuteSuccess, ServerCode.NotFoundResource))
        if response.code in (0, ServerCode.ExecuteSuccess):
            if (response.resource.name != request.name or response.resource.namespace != request.namespace
                    or not response.version.version or (request.version and response.version.version != request.version)):
                raise SDKError(ErrorCode.ErrCodeInvalidResponse, "Skill response identity or version mismatch")
        return response

    async def list_skills(self, request):
        """Query one remote page of published skills."""
        fields = ("namespace", "name", "tag", "owner", "scope", "keyword", "order_by", "order_type", "offset", "limit")
        return ensure_response(await self.connection._unary(
            "GetSkillList", pb.ListSkillsRequest(**{key: getattr(request, key) for key in fields}),
            timeout_seconds=(request.timeout or self.config.message_timeout) / 1000,
        ), (0, ServerCode.ExecuteSuccess, ServerCode.NotFoundResource))

    async def download_skill(self, request):
        """Reassemble one whole download; a retry always starts with an empty buffer."""
        connection = self.connection
        outgoing = pb.DownloadSkillRequest(namespace=request.namespace, name=request.name, version=request.version,
                                            tag=request.tag, format=request.format)
        attempts = connection.settings.retry_attempts + 1
        last_error = None
        for attempt in range(attempts):
            address = connection._addresses[connection._address_index % len(connection._addresses)]
            stream = None
            try:
                stub = await connection._stub(address)
                stream = stub.DownloadSkill(
                    outgoing, timeout=(request.timeout or (self.config.download_timeout if request.format == "zip"
                                                          else self.config.message_timeout)) / 1000,
                    metadata=_request_id("DownloadSkill") + connection._metadata(),
                )
                result = None
                chunks = []
                async for part in stream:
                    ensure_response(part, (0, ServerCode.ExecuteSuccess, ServerCode.NotFoundResource))
                    if result is None:
                        result = pb.DownloadSkillResponse()
                        result.CopyFrom(part)
                        result.zip_chunk = b""
                    else:
                        for key in ("version", "content_type", "filename", "total_size"):
                            value = getattr(part, key)
                            if value and getattr(result, key) and value != getattr(result, key):
                                raise SDKError(ErrorCode.ErrCodeInvalidResponse, f"inconsistent Skill download {key}")
                            if value:
                                setattr(result, key, value)
                        result.content += part.content
                    chunks.append(part.zip_chunk)
                    if part.code == ServerCode.NotFoundResource:
                        return part
                if result is None:
                    raise SDKError(ErrorCode.ErrCodeInvalidResponse, "empty Skill download stream")
                result.zip_chunk = b"".join(chunks)
                if request.version and result.version != request.version:
                    raise SDKError(ErrorCode.ErrCodeInvalidResponse, "Skill download returned a different version")
                size = len(result.zip_chunk) if request.format == "zip" else len(result.content.encode("utf-8"))
                if result.total_size and result.total_size != size:
                    raise SDKError(ErrorCode.ErrCodeInvalidResponse, "Skill download size mismatch")
                return result
            except grpc.aio.AioRpcError as error:
                last_error = error
                if error.code() not in connection._RETRYABLE_STATUS or attempt + 1 >= attempts:
                    break
                connection._address_index = (connection._address_index + 1) % len(connection._addresses)
                await asyncio.sleep(connection.settings.retry_backoff_seconds * 2**attempt)
            finally:
                if stream is not None:
                    cancel = getattr(stream, "cancel", None)
                    if cancel is not None:
                        cancel()
                    else:
                        close = getattr(stream, "aclose", None)
                        if close is not None:
                            await close()
        raise SDKError(ErrorCode.ErrCodeNetworkError, f"Polaris DownloadSkill failed: {last_error}") from last_error

    async def close(self):
        """Close only the Skill connection belonging to this context."""
        await self.connection.close()
