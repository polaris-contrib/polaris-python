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
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared admin HTTP server for stats and lossless endpoints."""

from __future__ import annotations

from aiohttp import web

import polaris.api.log as logger
from polaris.pkg.config.stat_reporter import AdminConfig
from polaris.pkg.model.error import ErrorCode, SDKError

admin_logger = logger.get_logger("admin")


class AdminHttpServer:
    """Expose one aiohttp application for every SDK component on the admin port."""

    def __init__(self, admin_config: AdminConfig):
        self.admin_config = admin_config
        self.app = web.Application()
        self.runner = None
        self.port = None
        self._routes = {}
        self._started = False

    def add_route(self, method: str, path: str, handler) -> None:
        key = (method, path)
        if key in self._routes:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           f"duplicated admin HTTP route {method} {path}")
        self._routes[key] = handler
        self.app.router.add_route(method, path, handler)

    def has_routes(self) -> bool:
        return bool(self._routes)

    async def start(self) -> None:
        """Bind the configured admin address once all routes have been added."""
        if self._started or not self._routes:
            return
        if self.admin_config.port is None or self.admin_config.port < 0:
            return
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.admin_config.host, self.admin_config.port)
        try:
            await site.start()
        except OSError as error:
            await self.runner.cleanup()
            self.runner = None
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig,
                           f"Cannot bind admin listener {self.admin_config.host}:{self.admin_config.port}: {error}") from error
        self.port = site._server.sockets[0].getsockname()[1]
        self._started = True
        admin_logger.warning("admin http server listen on %s:%s", self.admin_config.host, self.port)

    async def close(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None
        self._started = False
        self.port = None
