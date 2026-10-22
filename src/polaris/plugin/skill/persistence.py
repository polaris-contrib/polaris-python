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

"""Versioned Skill backups sharing the SDK's atomic writer and retry semantics."""

import os
from dataclasses import dataclass
from types import SimpleNamespace
from urllib.parse import quote_plus

from google.protobuf import json_format
from polarismesh_specification.api.v1.skill_manage import skill_service_pb2 as pb

from polaris.pkg.config.api import LocalCacheConfig
from polaris.plugin.local_registry.file_cache import LocalFileCache


@dataclass(frozen=True)
class SkillCacheKey:
    """Identify one persisted payload independently of instance resources."""

    namespace: str
    name: str
    version: str
    operation: str
    format: str = ""


class SkillPersistentHandler(LocalFileCache):
    """Persist complete responses and a last-seen active-version pointer."""

    def __init__(self, config, logger):
        cache = LocalCacheConfig(persist_dir=config.persist_dir,
                                 persist_max_read_retry=config.persist_max_read_retry,
                                 persist_max_write_retry=config.persist_max_write_retry,
                                 persist_retry_interval=config.persist_retry_interval)
        cache.set_default()
        context = SimpleNamespace(config=SimpleNamespace(get_consumer=lambda: SimpleNamespace(get_local_cache=lambda: cache)),
                                  logger=logger)
        super().__init__(context)
        self.max_write_retry = config.persist_max_write_retry
        self.max_read_retry = config.persist_max_read_retry

    def _copy_request(self, key):
        return key

    def _copy_response(self, data):
        snapshot = type(data)()
        snapshot.CopyFrom(data)
        return snapshot

    def _parse_response(self, key, buf):
        message = pb.DownloadSkillResponse() if key.operation == "download" else pb.GetSkillResponse()
        return json_format.Parse(buf.decode("utf-8"), message)

    def get_cache_file_path(self, key):
        parts = [key.namespace, key.name, key.version, key.operation, key.format]
        return os.path.join(self.base_dir, "skill#" + "#".join(quote_plus(part, safe="") for part in parts) + ".json")

    def save_success(self, request, response, operation):
        """Queue the resolved payload before publishing its active pointer."""
        version = response.version.version if operation == "get" else response.version
        if not version:
            return
        key = SkillCacheKey(request.namespace, request.name, version, operation, getattr(request, "format", ""))
        self.save(key, response)
        if not request.version:
            pointer = pb.GetSkillResponse(code=200000, version={"version": version})
            self.save(SkillCacheKey(request.namespace, request.name, "", "active"), pointer)

    async def load(self, request, operation):
        """Resolve a requested or last active version and load its complete payload."""
        version = request.version
        if not version:
            pointer = await self.async_get(SkillCacheKey(request.namespace, request.name, "", "active"), expire=None)
            if pointer is None:
                return None
            version = pointer.version.version
        if not version:
            return None
        return await self.async_get(SkillCacheKey(request.namespace, request.name, version, operation,
                                                getattr(request, "format", "")), expire=None)
