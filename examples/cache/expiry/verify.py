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

"""Verify real idle scanning, stream cleanup, backups and reload without external I/O."""

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import verification_directory

import asyncio
import copy
import json
from unittest.mock import patch

from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

from polaris import Configuration, ConsumerAPI, LogOptions, init_context_by_config
from polaris.pkg.model.server import InstanceDiscoverRequest

from main import run


class Stub:
    """Fake the server while retaining the SDK transport and cache implementation."""

    def __init__(self):
        self.opened = []
        self.closed = []
        self.requests = []

    async def ReportClient(self, request, timeout=None, metadata=()):
        return response_pb2.Response(code={"value": 200000})

    def Discover(self, requests, timeout=None, metadata=()):
        async def responses():
            key = None
            try:
                async for request in requests:
                    if key is None:
                        key = (request.service.namespace.value, request.service.name.value, request.type)
                        self.opened.append(key)
                    self.requests.append(copy.deepcopy(request))
                    response = response_pb2.DiscoverResponse(code={"value": 200000}, type=request.type,
                        service=service_pb2.Service(name=request.service.name, namespace=request.service.namespace,
                                                   revision={"value": "revision-1"}))
                    if request.type == 1:
                        response.instances.append(service_pb2.Instance(id={"value": "instance-1"},
                            service=request.service.name, namespace=request.service.namespace,
                            host={"value": "127.0.0.1"}, port={"value": 8080},
                            healthy={"value": True}, weight={"value": 100}))
                    yield response
            finally:
                if key is not None:
                    self.closed.append(key)
        return responses()


def verify(directory):
    """Wait for the actual 5-second idle threshold and 2.5-second scanner."""
    stub = Stub()
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = ["offline:8091"]
    config.get_global().get_api().bind_ip = "127.0.0.1"
    config.get_global().get_admin().port = 0
    config.get_consumer().get_local_cache().persist_dir = str(directory.parent / "polaris" / "backup")
    config.get_consumer().get_local_cache().service_expire_time = 5000
    originals = {}
    evictions = []

    async def fake_stub(connection, address):
        return stub

    with patch("polaris.plugin.server_connector.grpc_connector.connection.GrpcConnection._stub", fake_stub):
        context = init_context_by_config(
            config, log_options=LogOptions(log_dir=directory.parent / "polaris" / "log"))
        engine = context.get_engine()
        original_expire = engine.registry.expire_services

        async def capture_expiry():
            assert asyncio.get_running_loop() is engine.loop
            if not originals:
                originals.update(engine.registry.service_map)
            keys = await original_expire()
            if keys:
                assert not engine.registry.service_map
                assert not engine.registry.get_services()
                assert not engine.update_task_set
                assert engine.svc_connector._streams == engine.svc_connector._stream_locks == {}
                request = InstanceDiscoverRequest(1, "svc", "ns")
                assert not Path(engine.file_cache.get_cache_file_path(request)).exists()
                assert engine.file_cache.get(request) is None
                evictions.extend(keys)
            return keys

        engine.registry.expire_services = capture_expiry
        try:
            result = run(ConsumerAPI(context), "ns", "svc", 8)
            assert len(evictions) == 1
            assert result["initial_ids"] == result["reloaded_ids"] == ["instance-1"]
            assert all(originals[key] is not value for key, value in engine.registry.service_map.items())
            assert len(stub.opened) == 2
            assert len(stub.closed) == 1
            engine.file_cache.queue.join()
            assert engine.file_cache.get(InstanceDiscoverRequest(1, "svc", "ns")) is not None
        finally:
            context.destroy()
        assert len(stub.closed) == 2
        assert not engine.thread.is_alive()
        assert not engine.file_cache.write_thread.is_alive()
        assert engine.file_cache.lock_file.closed
        assert engine.update_task_set == engine.registry.service_map == {}
        print(json.dumps({"evicted_resources": len(evictions), "reopened_streams": 1,
                          "backups_deleted": True, "context_destroyed": context.is_destroy()}))


def main():
    """Run the offline verification with a retained run-local backup directory."""
    with verification_directory(__file__) as directory:
        verify(Path(directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
