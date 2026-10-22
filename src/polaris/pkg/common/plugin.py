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

from abc import abstractmethod

from polaris.pkg.config import api
from polaris.plugin_manager import PluginType


class Supplier:
    @abstractmethod
    def get_plugin(cls, type: PluginType, name: str):
        pass


class InitContext:
    def __init__(self, config: api.Configuration, plugins: Supplier, value_ctx, conn_manager):
        self.config = config
        self.plugins = plugins
        self.value_ctx = value_ctx
        self.conn_manager = conn_manager
