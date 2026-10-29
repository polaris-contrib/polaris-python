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

"""Public API for Java-compatible lossless online/offline."""

from polaris.api.config import SDKContext
from polaris.pkg.model.error import SDKError, ErrorCode
from polaris.pkg.model.lossless import LosslessActionProvider, LosslessInstance


class LosslessAPI:
    """Drive lossless lifecycle with user-supplied register/deregister callbacks."""

    def __init__(self, context: SDKContext):
        self.context = context

    def check_available(self):
        if not self.context:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "losslessAPI can not be None")
        if self.context.is_destroy():
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "losslessAPI: api instance has been destroyed")

    def _manager(self):
        manager = self.context.get_engine().lossless_manager
        if manager is None:
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "losslessAPI: engine has no lossless manager")
        return manager

    def set_lossless_action_provider(self, instance: LosslessInstance,
                                     provider: LosslessActionProvider) -> None:
        """Bind the callbacks used by lossless register/deregister for one instance."""
        self.check_available()
        if not isinstance(provider, LosslessActionProvider):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "losslessAPI: provider must implement LosslessActionProvider")
        self._manager().set_action_provider(instance, provider)

    def lossless_register(self, instance: LosslessInstance) -> None:
        """Synchronously start lossless online for one instance."""
        self.check_available()
        engine = self.context.get_engine()
        engine._run_sync(self._manager().lossless_register(instance))

    async def async_lossless_register(self, instance: LosslessInstance) -> None:
        """Asynchronously start lossless online for one instance."""
        self.check_available()
        engine = self.context.get_engine()
        await engine._run_async(self._manager().lossless_register(instance))

    def lossless_deregister(self, instance: LosslessInstance) -> None:
        """Synchronously trigger lossless offline for one instance."""
        self.check_available()
        engine = self.context.get_engine()
        engine._run_sync(self._manager().lossless_deregister(instance))

    async def async_lossless_deregister(self, instance: LosslessInstance) -> None:
        """Asynchronously trigger lossless offline for one instance."""
        self.check_available()
        engine = self.context.get_engine()
        await engine._run_async(self._manager().lossless_deregister(instance))
