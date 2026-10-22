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

from polaris.pkg.model.service import GetOneInstanceRequest, GetInstancesRequest
from polaris.pkg.flow.base_flow import CacheFilter, CacheResult
from polaris.pkg.flow.impl import Engine
from polaris.pkg.flow.base_flow import get_load_cache_values


class FutureRequest:
    def __init__(self, request: GetOneInstanceRequest, hash_value: int, do_load_balance: bool):
        self.request = request
        self.hash_value = hash_value
        self.do_load_balance = do_load_balance


class AsyncFlowFuture:
    def __init__(self, request: FutureRequest, filter_request: CacheFilter, redirect_times: int, engine: Engine):
        self.request = request
        self.filter_request = filter_request
        self.redirect_times = redirect_times
        self.engine = engine


class AsyncEngine(Engine):

    def create_async_flow_future(self, req: FutureRequest):
        future = AsyncFlowFuture(request=req)
        future.engine = AsyncEngine
        return future

    async def async_get_instances(self, req: GetInstancesRequest, do_balance: bool):
        req = self.set_default_value_for_instances_request(req)
        async_future = self.create_async_flow_future(req)
        async_future.filter_request = self.instance_request_to_cache_filter(req=req, redirect_service=None)
        request = async_future.filter_request
        result = await get_load_cache_values(self.registry, request, True)
        return result

    async def async_get_one_instance(self, req: GetOneInstanceRequest):
        instance_request = GetInstancesRequest(flow_id=req.flow_id, service=req.service, namespace=req.namespave,
                                               timeout=req.timeout)
        return await self.async_get_instances(instance_request, True)
