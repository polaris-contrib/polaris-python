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

"""Verify both weighted-random demo paths with real SDK plugins and fake registry RPCs."""

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import verification_directory

import json
from unittest.mock import patch

from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2
from polaris.api.consumer import ConsumerAPI
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection
from examples.loadbalancer.wr import main as demo


class Stub:
    async def ReportClient(self, request, timeout=None, metadata=()):
        return response_pb2.Response(code={"value": 200000})

    def Discover(self, requests, timeout=None, metadata=()):
        async def responses():
            async for request in requests:
                response = response_pb2.DiscoverResponse(code={"value": 200000}, type=request.type,
                    service=service_pb2.Service(name=request.service.name, namespace=request.service.namespace,
                                               revision={"value": "weighted-random"}))
                if request.type == 1:
                    for port, weight in ((8081, 25), (8082, 75)):
                        response.instances.append(service_pb2.Instance(id={"value": str(port)},
                            host={"value": "127.0.0.1"}, port={"value": port},
                            service=request.service.name, namespace=request.service.namespace,
                            healthy={"value": True}, weight={"value": weight}))
                yield response
        return responses()


def main():
    reported = {"sync": [], "async": []}
    original_sync = ConsumerAPI.sync_update_service_call_result
    original_async = ConsumerAPI.async_update_service_call_result

    def report_sync(consumer, result):
        reported["sync"].append(result.called_instance.get_id())
        return original_sync(consumer, result)

    async def report_async(consumer, result):
        reported["async"].append(result.called_instance.get_id())
        return await original_async(consumer, result)

    async def stub(connection, address):
        return Stub()

    with verification_directory(__file__), \
         patch.object(GrpcConnection, "_stub", stub), \
         patch.object(ConsumerAPI, "sync_update_service_call_result", report_sync), \
         patch.object(ConsumerAPI, "async_update_service_call_result", report_async):
        # Explicit SDK address avoids any external IP probe before the fake boundary.
        with patch.dict("os.environ", {"POLARIS_SERVER": "offline:8091"}):
            original = demo.Configuration.set_default

            def defaults(config):
                original(config)
                config.get_global().get_api().bind_ip = "127.0.0.1"

            with patch.object(demo.Configuration, "set_default", defaults):
                demo.main(["ns", "svc", "40", "--interval", "0"])
        assert all(len(values) == 40 and set(values) <= {"8081", "8082"} for values in reported.values())
        context = demo.CONSUMER_INSTANCE.context
        assert context.is_destroy() and not context.engine.thread.is_alive()
        assert not context.engine.file_cache.write_thread.is_alive()
        assert all(instance.handler.stream is None for instance in context.value_context.logger._categories.values())
        print(json.dumps({"sync_selections": 40, "async_selections": 40,
                          "reported_once_per_call": True, "context_destroyed": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
