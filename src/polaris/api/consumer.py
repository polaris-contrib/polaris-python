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

from polaris.pkg.config.api import Configuration
from polaris.pkg.model.service import (GetInstancesRequest, GetOneInstanceRequest, InstancesResponse,
                                      ServiceCallResult, Instance)
from polaris.pkg.model.rule import ServiceRuleResponse, GetServiceRuleRequest
from polaris.api.config import SDKContext, init_context_by_config, init_context_by_file
from polaris.api.log import LogOptions
from polaris.pkg.model.error import SDKError, ErrorCode
from polaris.pkg.flow.async_flow import CacheResult
from polaris.pkg.model.core import EventType
from polaris.pkg.model.event import SDKEventName, SDKEventType

class ServiceWatch:
    """An active instance watch owned by one ConsumerAPI."""

    def __init__(self, consumer, request, snapshot, listener=None):
        self._consumer = consumer
        self.namespace = request.namespace
        self.service = request.service
        self.instances = snapshot
        self.listener = listener
        self._lock = RLock()
        self._closed = False

    def close(self):
        """Stop this watch. Repeated close is harmless."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._consumer.unwatch_service(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class ConsumerAPI:
    def __init__(self, context: SDKContext):
        self.context = context

    def check_available(self):
        if not self.context:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "consumeAPI can not be None")
        if self.context.is_destroy():
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "consumeAPI: api instance has been destroyed")

    def get_one_instance(self, request: GetOneInstanceRequest) -> Instance:
        self.check_available()
        request.validate()

        return self.context.get_engine().sync_get_one_instance(request)

    def get_instances(self, request: GetInstancesRequest) -> InstancesResponse:
        """Return locally filtered candidates without selecting or consuming a half-open permit."""
        self.check_available()
        request.validate()

        return self.context.get_engine().sync_get_instances(request)

    def get_all_instances(self, request: GetInstancesRequest) -> InstancesResponse:
        """Return every cached instance, including isolated and unhealthy nodes."""
        self.check_available()
        request.validate()
        return self.context.get_engine().sync_get_all_instances(request)

    def get_healthy_instances(self, request: GetInstancesRequest) -> InstancesResponse:
        """Return candidates using only isolation and recovery filters."""
        self.check_available()
        request.validate()
        return self.context.get_engine().sync_get_healthy_instances(request)

    def get_services(self):
        """Return the service resources currently cached by this context."""
        self.check_available()
        return self.context.get_engine().sync_get_services()

    async def async_get_services(self):
        """Asynchronously return the service resources cached by this context."""
        self.check_available()
        return await self.context.get_engine().async_get_services()

    def sync_update_service_call_result(self, request: ServiceCallResult):
        self.check_available()
        request.validate()

        return self.context.get_engine().sync_update_service_call_result(request)

    async def async_get_one_instance(self, request: GetOneInstanceRequest) -> Instance:
        self.check_available()
        request.validate()

        return await self.context.get_engine().async_get_one_instance(req=request)

    async def async_get_instances(self, request: GetInstancesRequest) -> InstancesResponse:
        self.check_available()
        request.validate()

        return await self.context.get_engine().async_get_instances(req=request)

    async def async_get_all_instances(self, request: GetInstancesRequest) -> InstancesResponse:
        """Asynchronously return the full snapshot."""
        self.check_available()
        request.validate()
        return await self.context.get_engine().async_get_all_instances(request)

    async def async_get_healthy_instances(self, request: GetInstancesRequest) -> InstancesResponse:
        """Asynchronously return isolation and recovery candidates."""
        self.check_available()
        request.validate()
        return await self.context.get_engine().async_get_healthy_instances(request)

    def get_route_rule(self, request: GetServiceRuleRequest) -> ServiceRuleResponse:
        """Synchronously reject unsupported non-instance resource loading."""
        self.check_available()
        request.validate()
        raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument, "only instance resources are cached")

    async def async_get_route_rule(self, request: GetServiceRuleRequest) -> ServiceRuleResponse:
        """Asynchronously reject unsupported non-instance resource loading."""
        self.check_available()
        request.validate()
        return await self.context.get_engine().sync_get_service_rule(event_type=EventType.Routing, req=request)

    def watch_service(self, request: GetInstancesRequest, listener=None) -> ServiceWatch:
        """Load and pin one service, forwarding its cache lifecycle events."""
        if listener is not None and not callable(listener):
            raise ValueError("listener must be callable")
        snapshot = self.get_all_instances(request)
        return self._start_watch(request, snapshot, listener)

    async def async_watch_service(self, request: GetInstancesRequest, listener=None) -> ServiceWatch:
        """Asynchronously load and pin one service."""
        if listener is not None and not callable(listener):
            raise ValueError("listener must be callable")
        snapshot = await self.async_get_all_instances(request)
        return self._start_watch(request, snapshot, listener)

    def _start_watch(self, request, snapshot, listener):
        self.check_available()
        self.context.get_engine().registry.watch_service(request.namespace, request.service)
        event_center = self.context.get_event_center()
        if event_center is None:
            self.context.get_engine().registry.unwatch_service(request.namespace, request.service)
            raise SDKError(ErrorCode.ErrCodeInvalidStateError, "SDKContext event center is unavailable")

        def filtered_listener(event):
            if (event.event_type != SDKEventType.INSTANCE
                    or event.namespace != request.namespace
                    or event.service != request.service
                    or event.event_name not in (
                        SDKEventName.ON_SERVICE_ADDED,
                        SDKEventName.ON_SERVICE_UPDATED,
                        SDKEventName.ON_SERVICE_DELETED,
                    )):
                return
            if listener is not None:
                listener(event)

        event_center.register_listener(filtered_listener, SDKEventType.INSTANCE)
        watch = ServiceWatch(self, request, snapshot, listener)
        watch._event_listener = filtered_listener
        watch._event_center = event_center
        return watch

    def unwatch_service(self, watch: ServiceWatch):
        """Release a watch created by this ConsumerAPI."""
        if not isinstance(watch, ServiceWatch) or watch._consumer is not self:
            raise ValueError("watch must belong to this ConsumerAPI")
        with watch._lock:
            watch._closed = True
            if getattr(watch, "_event_center", None) is not None:
                watch._event_center.unregister_listener(
                    watch._event_listener, SDKEventType.INSTANCE,
                )
                watch._event_center = None
            if self.context is not None and not self.context.is_destroy():
                self.context.get_engine().registry.unwatch_service(watch.namespace, watch.service)

    async def async_unwatch_service(self, watch: ServiceWatch):
        """Asynchronously release a watch created by this ConsumerAPI."""
        self.unwatch_service(watch)

    def update_service_call_result(self, request: ServiceCallResult):
        """Synchronously report invocation metrics and the existing local instance result."""
        return self.sync_update_service_call_result(request)

    async def async_update_service_call_result(self, request: ServiceCallResult):
        """Asynchronously report invocation metrics on this context's owner loop."""
        self.check_available()
        request.validate()

        return await self.context.get_engine().async_update_service_call_result(request)

    def get_service_contract(self, request):
        """Synchronously fetch a contract from the registry."""
        self.check_available()
        request.validate()
        return self.context.get_engine().sync_contract_call("get_service_contract", request)

    async def async_get_service_contract(self, request):
        """Asynchronously fetch a contract from the registry."""
        self.check_available()
        request.validate()
        return await self.context.get_engine().async_contract_call("get_service_contract", request)

    def destroy(self):
        if self.context:
            self.context.destroy()


def create_consumer_by_file(path: str, *, log_options: LogOptions | None = None) -> ConsumerAPI:
    context = init_context_by_file(path, log_options=log_options)
    return ConsumerAPI(context)


def create_consumer_by_config(config: Configuration, *, log_options: LogOptions | None = None) -> ConsumerAPI:
    context = init_context_by_config(config, log_options=log_options)
    return ConsumerAPI(context)


def create_consumer_by_default_config_file(*, log_options: LogOptions | None = None) -> ConsumerAPI:
    from polaris.api.config import init_context
    return ConsumerAPI(context=init_context(log_options=log_options))
