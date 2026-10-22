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

"""Public request and result models for the read-only Skill API."""

from dataclasses import dataclass, field

from polaris.pkg.model.error import ErrorCode, SDKError


@dataclass
class SkillGetRequest:
    """Fetch a published skill, using the active version when version is empty."""

    namespace: str
    name: str
    version: str = ""
    timeout: int = 0

    def validate(self):
        """Validate the resource identity and optional timeout in milliseconds."""
        if (not isinstance(self.namespace, str) or not self.namespace.strip()
                or not isinstance(self.name, str) or not self.name.strip() or not isinstance(self.version, str)
                or type(self.timeout) is not int or self.timeout < 0):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "skill namespace/name are required and timeout must be >=0")


@dataclass
class SkillListRequest:
    """Search published skills with filters, sorting and pagination."""

    namespace: str = ""
    name: str = ""
    tag: str = ""
    owner: str = ""
    scope: str = ""
    keyword: str = ""
    order_by: str = ""
    order_type: str = ""
    offset: int = 0
    limit: int = 100
    timeout: int = 0

    def validate(self):
        """Validate pagination and optional request timeout."""
        if (type(self.offset) is not int or type(self.limit) is not int or type(self.timeout) is not int
                or self.offset < 0 or self.limit < 0 or self.timeout < 0):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "skill offset, limit and timeout must be nonnegative integers")


@dataclass
class SkillDownloadRequest(SkillGetRequest):
    """Download a skill as markdown or a complete ZIP archive."""

    tag: str = ""
    format: str = "markdown"

    def validate(self):
        """Validate the identity and supported download format."""
        super().validate()
        if self.format not in ("markdown", "zip"):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "skill format must be markdown or zip")


@dataclass
class SkillVersionInfo:
    """Version pointers published by the registry."""

    active_version: str = ""
    latest_version: str = ""
    total_versions: int = 0


@dataclass
class SkillStorageInfo:
    """Storage metadata for a skill package."""

    provider: str = ""
    files: list[str] = field(default_factory=list)
    scope: str = ""
    content_digest: str = ""


@dataclass
class SkillResource:
    """Registry metadata describing a published skill."""

    id: int = 0
    name: str = ""
    namespace: str = ""
    description: str = ""
    status: str = ""
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    ext: dict[str, str] = field(default_factory=dict)
    source: str = ""
    version_info: SkillVersionInfo = field(default_factory=SkillVersionInfo)
    meta_version: int = 0
    scope: str = ""
    owner: str = ""
    download_count: int = 0
    create_time: str = ""
    modify_time: str = ""


@dataclass
class SkillResourceVersion:
    """Metadata for the resolved published version."""

    id: int = 0
    name: str = ""
    namespace: str = ""
    version: str = ""
    author: str = ""
    description: str = ""
    status: str = ""
    storage: SkillStorageInfo = field(default_factory=SkillStorageInfo)
    download_count: int = 0
    create_time: str = ""
    modify_time: str = ""


@dataclass
class SkillGetResponse:
    """A published skill and its SKILL.md content."""

    resource: SkillResource
    version: SkillResourceVersion
    content: str
    loaded_from_file: bool = False
    code: int = 200000
    info: str = ""


@dataclass
class SkillListResponse:
    """One page of skill search results."""

    total: int
    resources: list[SkillResource]
    code: int = 200000
    info: str = ""


@dataclass
class SkillDownloadResponse:
    """A complete markdown document or ZIP package."""

    version: str
    content_type: str
    content: str = ""
    data: bytes = b""
    total_size: int = 0
    filename: str = ""
    loaded_from_file: bool = False
    code: int = 200000
    info: str = ""
