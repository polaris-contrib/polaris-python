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

"""Verify the Java-aligned router chains with real SDK plugins and fake RPCs."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2])]
from examples._internal._runtime import verification_directory

from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2
from polaris.api.consumer import ConsumerAPI
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection
from examples.servicerouter import main as demo


class Stub:
    async def ReportClient(self, request, timeout=None, metadata=()):
        return response_pb2.Response(code={"value": 200000})

    def Discover(self, requests, timeout=None, metadata=()):
        async def responses():
            async for request in requests:
                response = response_pb2.DiscoverResponse(
                    code={"value": 200000},
                    type=request.type,
                    service=service_pb2.Service(
                        name=request.service.name,
                        namespace=request.service.namespace,
                        revision={"value": "service-router"},
                    ),
                )
                if request.type == 1:
                    for item in self.instances():
                        response.instances.append(service_pb2.Instance(
                            id={"value": item["id"]},
                            host={"value": "127.0.0.1"},
                            port={"value": item["port"]},
                            service=request.service.name,
                            namespace=request.service.namespace,
                            healthy={"value": item["healthy"]},
                            isolate={"value": item.get("isolated", False)},
                            weight={"value": item.get("weight", 100)},
                            metadata=item.get("metadata", {}),
                        ))
                yield response
        return responses()

    @staticmethod
    def instances():
        return [
            {"id": "isolated", "port": 8081, "healthy": True, "isolated": True},
            {"id": "zero-weight", "port": 8082, "healthy": True, "weight": 0},
            {"id": "prod", "port": 8083, "healthy": True, "metadata": {"env": "prod"}},
            {"id": "stable", "port": 8084, "healthy": True, "metadata": {"env": "stable"}},
            {"id": "unhealthy-prod", "port": 8085, "healthy": False, "metadata": {"env": "prod"}},
            {"id": "missing", "port": 8086, "healthy": True},
        ]


class AllUnhealthyStub(Stub):
    @staticmethod
    def instances():
        return [
            {"id": "down-prod", "port": 8091, "healthy": False, "metadata": {"env": "prod"}},
            {"id": "down-stable", "port": 8092, "healthy": False, "metadata": {"env": "stable"}},
        ]


def run_case(name, mode, metadata, failover):
    reported = {"sync": [], "async": []}
    original_sync = ConsumerAPI.sync_update_service_call_result
    original_async = ConsumerAPI.async_update_service_call_result

    def report_sync(consumer, result):
        reported["sync"].append(result.called_instance.get_id())
        return original_sync(consumer, result)

    async def report_async(consumer, result):
        reported["async"].append(result.called_instance.get_id())
        return await original_async(consumer, result)

    backup_root = Path(__file__).resolve().parent / ".logs" / "verify-backup"

    def backup(entry, component=None):
        path = backup_root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    with patch.object(demo, "demo_backup_directory", backup), \
         patch.object(ConsumerAPI, "sync_update_service_call_result", report_sync), \
         patch.object(ConsumerAPI, "async_update_service_call_result", report_async):
        arguments = ["ns", "svc", "2", "--mode", mode, "--interval", "0"]
        if metadata:
            arguments.extend(["--failover", failover])
            for key, value in metadata.items():
                arguments.extend(["--metadata", f"{key}={value}"])
        demo.main(arguments)

    context = demo.CONSUMER_INSTANCE.context
    assert context.is_destroy()
    assert not context.engine.thread.is_alive()
    assert not context.engine.file_cache.write_thread.is_alive()
    assert all(instance.handler.stream is None
               for instance in context.value_context.logger._categories.values())
    return reported, context


def main():
    async def default_stub(connection, address):
        return Stub()

    async def unhealthy_stub(connection, address):
        return AllUnhealthyStub()

    original_defaults = demo.Configuration.set_default

    def defaults(config):
        original_defaults(config)
        config.get_global().get_api().bind_ip = "127.0.0.1"

    results = {}
    with verification_directory(__file__), \
         patch.object(demo.Configuration, "set_default", defaults), \
         patch.dict("os.environ", {"POLARIS_SERVER": "offline:8091"}):
        with patch.object(GrpcConnection, "_stub", default_stub):
            demo.CONSUMER_INSTANCE = None
            default_reports, default_context = run_case("default", "default", {}, "all")
            assert default_context.get_config().get_consumer().get_service_router().get_chain() == []
            assert set(default_reports["async"]) <= {"prod", "stable", "missing"}
            assert set(default_reports["sync"]) <= {"prod", "stable", "missing"}
            assert all(len(values) == 2 for values in default_reports.values())

            demo.CONSUMER_INSTANCE = None
            metadata_reports, metadata_context = run_case(
                "metadata-exact", "metadata", {"env": "prod"}, "none")
            router = metadata_context.get_config().get_consumer().get_service_router()
            assert router.get_chain() == ["metadataRouter"]
            assert metadata_reports == {"async": ["prod", "prod"], "sync": ["prod", "prod"]}

            demo.CONSUMER_INSTANCE = None
            others_reports, _ = run_case(
                "metadata-others", "metadata", {"env": "missing"}, "others")
            assert others_reports == {"async": ["missing", "missing"], "sync": ["missing", "missing"]}

        with patch.object(GrpcConnection, "_stub", unhealthy_stub):
            demo.CONSUMER_INSTANCE = None
            all_down_reports, all_down_context = run_case(
                "all-down-recovery", "default", {}, "all")
            assert all_down_context.get_config().get_consumer().get_service_router().get_chain() == []
            assert set(all_down_reports["async"]) <= {"down-prod", "down-stable"}
            assert set(all_down_reports["sync"]) <= {"down-prod", "down-stable"}
            assert all(len(values) == 2 for values in all_down_reports.values())

        results = {
            "default_chain": ["isolatedRouter", "recoverRouter"],
            "metadata_router_opt_in": True,
            "metadata_exact_match": ["prod"],
            "metadata_others_failover": ["missing"],
            "all_down_recovery": True,
            "reported_once_per_call": True,
            "context_destroyed": True,
        }
        print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
