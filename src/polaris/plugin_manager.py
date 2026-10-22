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

from threading import RLock

from polaris.pkg.model.context import ValueContext
from polaris.pkg.config.api import Configuration
from polaris.pkg.model.error import ErrorCode, SDKError


class PluginType:
    SERVER_CONNECTOR = 2
    SERVICE_ROUTER = 3
    LOAD_BALANCE = 4
    CIRCUIT_BREAKER = 5
    LOCAL_CACHE = 6
    STAT_REPORTER = 7
    SKILL_CONNECTOR = 8


class EventType:
    ON_LOCALVALUE_CREATED = 1


class PluginManager:
    """Own plugin instances and event subscribers for one SDK context."""

    def __init__(self):
        self.plugin_container = {}
        self.plugin_instance = {}
        self.event_handle_map = {}
        self._lock = RLock()

    def register(self, plugin_type: PluginType, plugin_name: str, plugin_cls):
        """Register a plugin constructor without creating a runtime instance."""
        with self._lock:
            self.plugin_container.setdefault(plugin_type, {})[plugin_name] = plugin_cls

    def new_context_manager(self):
        """Copy registered constructors into an empty, independent runtime manager."""
        manager = PluginManager()
        with self._lock:
            manager.plugin_container = {typ: dict(plugins) for typ, plugins in self.plugin_container.items()}
        return manager

    def get(self, plugin_type: PluginType, plugin_name: str):
        """Return a registered plugin constructor."""
        if plugin_type in self.plugin_container:
            return self.plugin_container[plugin_type][plugin_name]
        else:
            return ""

    def find_instance(self, plugin_type: PluginType, plugin_name: str) -> bool:
        """Check whether this context has created a plugin instance."""
        if plugin_type in self.plugin_instance and plugin_name in self.plugin_instance[plugin_type]:
            return True
        return False

    def get_instance(self, plugin_type: PluginType, plugin_name: str):
        """Return this context's plugin instance or a configuration diagnostic."""
        try:
            return self.plugin_instance[plugin_type][plugin_name]
        except KeyError as error:
            raise SDKError(ErrorCode.ErrCodePluginError,
                           f"Plugin is not available: {plugin_type}:{plugin_name}") from error

    def set_instance(self, plugin_type: PluginType, plugin_name: str, instance):
        """Store an instance owned exclusively by this context."""
        if plugin_type not in self.plugin_instance:
            self.plugin_instance[plugin_type] = {}

        self.plugin_instance[plugin_type][plugin_name] = instance

    def clear_instances(self):
        """Forget this context's instances and their event subscribers."""
        self.plugin_instance.clear()
        self.event_handle_map.clear()

    def destroy_plugins(self):
        """Release synchronous plugin resources after the owner loop has stopped."""
        instances = [instance for plugins in self.plugin_instance.values() for instance in plugins.values()]
        self.clear_instances()
        first_error = None
        for instance in reversed(instances):
            destroy = getattr(instance, "destroy", None)
            if destroy is not None:
                try:
                    destroy()
                except Exception as error:
                    if first_error is None:
                        first_error = error
        if first_error is not None:
            raise first_error

    def register_event_handle(self, event_type, handler):
        """Subscribe a context-owned handler to a plugin event."""
        self.event_handle_map.setdefault(event_type, []).append(handler)

    def get_event_subscriber(self, event_type):
        """Return only this context's subscribers, or an empty tuple."""
        return tuple(self.event_handle_map.get(event_type, ()))


def register_plugin(plugin_type: PluginType, plugin_name: str):
    def decorator(cls):
        DefaultPluginManager.register(plugin_type, plugin_name, cls)
        return cls

    return decorator


# Process-wide registration stores constructors only, never SDK runtime state.
DefaultPluginManager = PluginManager()


class InitContext:
    """Provide configuration and context-owned dependencies during plugin creation."""

    def __init__(self, config: Configuration = None, value_ctx: ValueContext = None,
                 plugins: PluginManager = None):
        self.config = config
        self.value_ctx = value_ctx
        self.plugins = plugins if plugins is not None else PluginManager()
        self.logger = getattr(value_ctx, "logger", None)


def setup(init_ctx: InitContext):
    """Create plugins in the supplied context manager, leaving the registry untouched."""
    manager = init_ctx.plugins
    for plugin_type, plugins in manager.plugin_container.items():
        for plugin_name, plugin in plugins.items():
            if not manager.find_instance(plugin_type, plugin_name):
                manager.set_instance(plugin_type, plugin_name, plugin(init_ctx))
