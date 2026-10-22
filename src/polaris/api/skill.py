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

"""Read-only published Skill APIs with synchronous and asynchronous entry points."""

from polaris.api.config import init_context_by_config, init_context_by_file
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.pkg.model.service import ExtendedMetadata, ServiceInstances
from polaris.pkg.model.skill import SkillDownloadRequest, SkillGetRequest, SkillListRequest


class SkillAPI:
    """Query and download published skills through a shared SDK context."""

    def __init__(self, context, *, owns_context=False):
        self.context = context
        self._owns_context = owns_context
        self._closed = False

    def _check(self, request):
        if self._closed or self.context is None or self.context.is_destroy():
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "Skill API or context has been destroyed")
        request.validate()

    def resolve_mounted_skill_request(self, service_snapshot, *, skill_name: str = "",
                                      requested_version: str = "", timeout: int = 0) -> SkillGetRequest:
        """Resolve one mounted skill, preferring its recorded version over the caller version."""
        if self._closed or self.context is None or self.context.is_destroy():
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "Skill API or context has been destroyed")
        if not isinstance(service_snapshot, ServiceInstances):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "service_snapshot must be a ServiceInstances")
        if not isinstance(skill_name, str) or not isinstance(requested_version, str) or type(timeout) is not int:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "skill_name and requested_version must be strings and timeout must be an integer")

        mounts = [item.agent_skill for item in service_snapshot.get_extended_metadata()
                  if item.type == ExtendedMetadata.SKILL and item.agent_skill is not None]
        if skill_name:
            mounts = [mount for mount in mounts if mount.name == skill_name]
        elif len(mounts) > 1:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "service has multiple mounted skills; specify skill_name")
        if not mounts:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "service has no matching mounted skill")

        mount = mounts[0]
        if not mount.name:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "mounted skill name is empty")
        version = mount.version or requested_version
        request = SkillGetRequest(service_snapshot.get_namespace(), mount.name, version, timeout)
        request.validate()
        return request

    def get_skill(self, request: SkillGetRequest):
        """Synchronously fetch published content with network-error fallback."""
        self._check(request)
        return self.context.engine.sync_skill_call("get_skill", request)

    async def async_get_skill(self, request: SkillGetRequest):
        """Asynchronously fetch published content with network-error fallback."""
        self._check(request)
        return await self.context.engine.async_skill_call("get_skill", request)

    def list_skills(self, request: SkillListRequest):
        """Synchronously search published skills on the remote server."""
        self._check(request)
        return self.context.engine.sync_skill_call("list_skills", request)

    async def async_list_skills(self, request: SkillListRequest):
        """Asynchronously search published skills on the remote server."""
        self._check(request)
        return await self.context.engine.async_skill_call("list_skills", request)

    def download_skill(self, request: SkillDownloadRequest):
        """Synchronously download a complete markdown or ZIP payload."""
        self._check(request)
        return self.context.engine.sync_skill_call("download_skill", request)

    def get_mounted_skill(self, service_snapshot, *, skill_name: str = "", requested_version: str = "",
                          timeout: int = 0):
        """Synchronously fetch the skill mounted on a discovered service."""
        request = self.resolve_mounted_skill_request(
            service_snapshot, skill_name=skill_name, requested_version=requested_version, timeout=timeout)
        return self.get_skill(request)

    async def async_get_mounted_skill(self, service_snapshot, *, skill_name: str = "",
                                      requested_version: str = "", timeout: int = 0):
        """Asynchronously fetch the skill mounted on a discovered service."""
        request = self.resolve_mounted_skill_request(
            service_snapshot, skill_name=skill_name, requested_version=requested_version, timeout=timeout)
        return await self.async_get_skill(request)

    def download_mounted_skill(self, service_snapshot, *, skill_name: str = "", requested_version: str = "",
                               timeout: int = 0, format: str = "markdown"):
        """Synchronously download the skill mounted on a discovered service."""
        request = self.resolve_mounted_skill_request(
            service_snapshot, skill_name=skill_name, requested_version=requested_version, timeout=timeout)
        download = SkillDownloadRequest(request.namespace, request.name, request.version, timeout, format=format)
        return self.download_skill(download)

    async def async_download_mounted_skill(self, service_snapshot, *, skill_name: str = "",
                                           requested_version: str = "", timeout: int = 0,
                                           format: str = "markdown"):
        """Asynchronously download the skill mounted on a discovered service."""
        request = self.resolve_mounted_skill_request(
            service_snapshot, skill_name=skill_name, requested_version=requested_version, timeout=timeout)
        download = SkillDownloadRequest(request.namespace, request.name, request.version, timeout, format=format)
        return await self.async_download_skill(download)

    async def async_download_skill(self, request: SkillDownloadRequest):
        """Asynchronously download a complete markdown or ZIP payload."""
        self._check(request)
        return await self.context.engine.async_skill_call("download_skill", request)

    def destroy(self):
        """Close this API and its context only when the factory created that context."""
        self._closed = True
        if self._owns_context and self.context is not None:
            self.context.destroy()


def create_skill_by_config(config, *, log_options=None):
    """Create a Skill API owning an independently configured context."""
    return SkillAPI(init_context_by_config(config, log_options=log_options), owns_context=True)


def create_skill_by_file(path, *, log_options=None):
    """Create a Skill API owning a context loaded from polaris.yaml."""
    return SkillAPI(init_context_by_file(path, log_options=log_options), owns_context=True)
