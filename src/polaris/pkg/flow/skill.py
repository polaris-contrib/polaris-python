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

"""Read-only Skill orchestration with network-error persistence fallback."""

from dataclasses import fields

from polaris.pkg.model.error import ErrorCode, SDKError, ServerCode
from polaris.pkg.model.skill import (
    SkillDownloadResponse, SkillGetResponse, SkillListResponse, SkillResource,
    SkillResourceVersion, SkillStorageInfo, SkillVersionInfo,
)
from polaris.plugin.skill.persistence import SkillPersistentHandler


def _resource(proto):
    values = {item.name: getattr(proto, item.name) for item in fields(SkillResource)}
    values.update(tags=list(proto.tags), examples=list(proto.examples), ext=dict(proto.ext),
                  version_info=SkillVersionInfo(proto.version_info.active_version,
                                               proto.version_info.latest_version, proto.version_info.total_versions))
    return SkillResource(**values)


def _version(proto):
    values = {item.name: getattr(proto, item.name) for item in fields(SkillResourceVersion)}
    values["storage"] = SkillStorageInfo(proto.storage.provider, list(proto.storage.files),
                                         proto.storage.scope, proto.storage.content_digest)
    return SkillResourceVersion(**values)


class SkillFlow:
    """Run Skill reads on a context's owner loop and persist successful responses."""

    def __init__(self, connector, config, logger):
        self.connector = connector
        self.config = config
        self.logger = logger
        self.persistence = None
        if config.persist_enable:
            try:
                self.persistence = SkillPersistentHandler(config, logger)
            except OSError as error:
                self.logger.warning("Skill backup initialization failed; using remote reads only: %s", error)

    async def _read(self, request, operation):
        loaded = False
        try:
            method = self.connector.get_skill if operation == "get" else self.connector.download_skill
            result = await method(request)
        except SDKError as error:
            if (error.err_code != ErrorCode.ErrCodeNetworkError or not self.config.fallback_to_local_cache
                    or self.persistence is None):
                raise
            result = await self.persistence.load(request, operation)
            if result is None or result.code not in (0, ServerCode.ExecuteSuccess):
                raise error
            loaded = True
            self.logger.warning("use local Skill backup for %s/%s", request.namespace, request.name)
        if loaded:
            version = result.version.version if operation == "get" else result.version
            if (not version or (request.version and request.version != version)
                    or (operation == "get" and (result.resource.name != request.name
                                                or result.resource.namespace != request.namespace))):
                raise SDKError(ErrorCode.ErrCodeInvalidResponse, "Skill backup identity or version mismatch")
            if operation == "download" and result.total_size:
                size = len(result.zip_chunk) if request.format == "zip" else len(result.content.encode("utf-8"))
                if size != result.total_size:
                    raise SDKError(ErrorCode.ErrCodeInvalidResponse, "Skill backup size mismatch")
        if not loaded and result.code in (0, ServerCode.ExecuteSuccess) and self.persistence is not None:
            try:
                self.persistence.save_success(request, result, operation)
            except (OSError, SDKError) as error:
                self.logger.warning("failed to persist Skill %s/%s: %s", request.namespace, request.name, error)
        return result, loaded

    async def get_skill(self, request):
        """Fetch published content with network-only local fallback."""
        response, loaded = await self._read(request, "get")
        return SkillGetResponse(_resource(response.resource), _version(response.version), response.content,
                                loaded, response.code, response.info)

    async def list_skills(self, request):
        """Fetch remote search results without storing or falling back to a list."""
        response = await self.connector.list_skills(request)
        return SkillListResponse(response.total, [_resource(item) for item in response.resources],
                                 response.code, response.info)

    async def download_skill(self, request):
        """Return one complete download with network-only local fallback."""
        response, loaded = await self._read(request, "download")
        return SkillDownloadResponse(response.version, response.content_type, response.content,
                                     response.zip_chunk, response.total_size, response.filename, loaded,
                                     response.code, response.info)

    def destroy(self):
        """Drain pending backups when the context closes."""
        if self.persistence is not None:
            self.persistence.destroy()
