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

from polaris import plugin_manager
from polaris.pkg.flow.impl import create_flow_engine, BaseEngine
from polaris.pkg.config.api import Configuration
from polaris.pkg.model.error import SDKError, ErrorCode
from polaris.pkg.model import context
from threading import RLock
import copy

from polaris.api.log import ContextLogger, LogOptions, use_context_logger


class SDKContext(object):
    """Own the configuration, plugins and runtime for an independent SDK client."""
    def __init__(self, config: Configuration, plugins: plugin_manager.PluginManager, engine: BaseEngine,
                 value_context: context.ValueContext = None, destroyed: int = 0):
        self.config = config
        self.plugins = plugins
        self.engine = engine
        self.value_context = value_context if value_context is not None else context.new_value_context()
        self._destroy_lock = RLock()
        # 标识是否已经销毁，0未销毁，1已销毁
        self.destroyed = destroyed
        self._cleaned_up = False
        add_callback = getattr(self.engine, "add_destroy_callback", None)
        if add_callback is not None:
            add_callback(self._cleanup)

    def _cleanup(self):
        if self._cleaned_up:
            return
        self._cleaned_up = True
        try:
            self.plugins.destroy_plugins()
        finally:
            self.value_context.clear()
            if self.value_context.logger is not None:
                self.value_context.logger.close()

    def destroy(self):
        """Release only this context's resources; repeated destruction is harmless."""
        with self._destroy_lock:
            if self.is_destroy():
                return
            self.destroyed = 1
            try:
                self.engine.destroy()
            finally:
                if getattr(self.engine, "add_destroy_callback", None) is None:
                    self._cleanup()

    def is_destroy(self):
        """Report whether this client is no longer available."""
        return self.destroyed > 0

    def get_config(self):
        """Return the configuration belonging to this client."""
        return self.config

    def get_plugins(self):
        """Return this client's plugin manager."""
        return self.plugins

    def get_engine(self):
        """Return the runtime owned by this client."""
        return self.engine

    def get_value_context(self):
        """Return this client's identity and runtime values."""
        return self.value_context

    def get_client_id(self) -> str:
        """Return the unique, stable client ID sent to Polaris."""
        return self.value_context.get_client_id()


def init_context_by_file(path: str, apply_env: bool = True, *, log_options: LogOptions | None = None):
    """Initialize an SDK context from a YAML file."""
    return init_context_by_config(Configuration.from_file(path, apply_env=apply_env), log_options=log_options)


def init_context_by_stream(buf, apply_env: bool = True, *, log_options: LogOptions | None = None):
    """Initialize an SDK context from YAML text or bytes."""
    from polaris.pkg.config.loader import build_configuration, parse_config_stream
    return init_context_by_config(
        build_configuration(parse_config_stream(buf), apply_env=apply_env), log_options=log_options,
    )


def init_context(*, log_options: LogOptions | None = None):
    """Initialize an SDK context from the default file or environment."""
    from polaris.pkg.config.loader import find_default_config_file

    config_file = find_default_config_file()
    if config_file is not None:
        return init_context_by_file(str(config_file), log_options=log_options)
    return init_context_by_config(Configuration.from_env(), log_options=log_options)


def init_context_by_config(config: Configuration, *, log_options: LogOptions | None = None):
    """Initialize from assigned configuration values without loading files or environment overrides."""
    config = copy.deepcopy(config)
    config.set_default()
    config.verify()
    global_ctx = context.new_value_context()
    global_ctx.logger = ContextLogger(global_ctx.get_client_id(), log_options)
    plugins = plugin_manager.DefaultPluginManager.new_context_manager()
    try:
        with use_context_logger(global_ctx.logger):
            engine = create_flow_engine(config, plugins, global_ctx)
    except Exception:
        try:
            plugins.destroy_plugins()
        finally:
            global_ctx.clear()
            global_ctx.logger.close()
        raise
    return SDKContext(config=config, plugins=plugins, engine=engine, value_context=global_ctx)
