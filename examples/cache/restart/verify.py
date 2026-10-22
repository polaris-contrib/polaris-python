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

"""Verify abrupt process termination and offline restart with a loopback gRPC server."""

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import verification_directory

import argparse
import asyncio
import json
import os
import signal
import threading
import time
from unittest.mock import patch

import grpc
from polarismesh_specification.api.v1.service_manage import grpcapi_pb2_grpc, response_pb2, service_pb2

from polaris import Configuration, ConsumerAPI, LogOptions, init_context_by_config
from polaris.pkg.model.server import InstanceDiscoverRequest
from polaris.pkg.model.service import GetInstancesRequest

from main import describe, run


class Server(grpcapi_pb2_grpc.PolarisGRPCServicer):
    """Serve complete instance snapshots through the actual Polaris gRPC transport."""

    def __init__(self, revision="revision-1"):
        self.revision = revision

    async def ReportClient(self, request, context):
        return response_pb2.Response(code={"value": 200000})

    async def Discover(self, requests, context):
        async for request in requests:
            response = response_pb2.DiscoverResponse(code={"value": 200000}, type=request.type,
                service=service_pb2.Service(name=request.service.name, namespace=request.service.namespace,
                                           revision={"value": self.revision}))
            if request.type == 1:
                response.instances.append(service_pb2.Instance(id={"value": "instance-1"},
                    service=request.service.name, namespace=request.service.namespace,
                    host={"value": "192.0.2.1"}, port={"value": 8080},
                    healthy={"value": True}, weight={"value": 100}))
            yield response


def child(directory, address, mode):
    """Run SDK startup in a separate process without replacing SDK/cache behavior."""
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = [address]
    config.get_global().get_api().bind_ip = "127.0.0.1"
    config.get_global().get_api().timeout = 100
    config.get_global().get_admin().port = -1
    config.get_consumer().get_local_cache().persist_dir = str(directory.parent / "polaris" / "backup")
    context = init_context_by_config(
        config, log_options=LogOptions(log_dir=directory.parent / "polaris" / "log" / mode))
    engine = context.get_engine()
    try:
        consumer = ConsumerAPI(context)
        if mode == "seed":
            result = asyncio.run(run(consumer, "ns", "svc"))
            engine.file_cache.queue.join()
            previous = engine.file_cache.get(InstanceDiscoverRequest(1, "svc", "ns"))
            previous.service.revision.value = "must-not-be-visible"

            def interrupted_replace(source, destination):
                print(json.dumps({"ready": True, **result}), flush=True)
                # Leave a synced temporary file, then terminate without SDK cleanup.
                threading.Event().wait()

            with patch("polaris.plugin.local_registry.file_cache.os.replace", interrupted_replace):
                engine.file_cache.save(InstanceDiscoverRequest(1, "svc", "ns"), previous)
                threading.Event().wait()
        elif mode == "sync":
            print(json.dumps(describe(consumer.get_instances(GetInstancesRequest(namespace="ns", service="svc")))),
                  flush=True)
        else:
            print(json.dumps(asyncio.run(run(consumer, "ns", "svc"))), flush=True)
    finally:
        context.destroy()
    assert not engine.thread.is_alive()
    assert not engine.file_cache.write_thread.is_alive()
    assert all(not thread.is_alive() for thread in engine.file_cache._read_executor._threads)


async def start_child(directory, address, mode):
    return await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).resolve()),
        "--child", mode, "--directory", str(directory), "--address", address,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, close_fds=False)


async def verify(directory):
    server = grpc.aio.server()
    grpcapi_pb2_grpc.add_PolarisGRPCServicer_to_server(Server(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    assert port > 0
    await server.start()
    address = f"127.0.0.1:{port}"
    seed = None
    try:
        seed = await start_child(directory, address, "seed")
        line = await asyncio.wait_for(seed.stdout.readline(), 15)
        if not line:
            _, errors = await seed.communicate()
            raise AssertionError(errors.decode())
        ready = json.loads(line)
        assert ready.pop("ready") is True
        assert ready["instance_revision"] == "revision-1"
        seed.kill()
        await asyncio.wait_for(seed.communicate(), 5)
        assert seed.returncode == -signal.SIGKILL
    finally:
        if seed is not None and seed.returncode is None:
            seed.kill()
            await seed.communicate()
        await server.stop(None)

    backup = directory.parent / "polaris" / "backup"
    assert len(list(backup.glob("*.tmp"))) >= 1
    cache_files = sorted(backup.glob("svc#ns#svc#*.json"))
    assert [file.name for file in cache_files] == ["svc#ns#svc#instance.json"]
    stored = json.loads(cache_files[0].read_text(encoding="utf-8"))
    assert stored["service"]["revision"] == "revision-1"
    for age in (0, 120):
        os.utime(cache_files[0], (time.time() - age, time.time() - age))
        for mode in ("sync", "async"):
            process = await start_child(directory, address, mode)
            try:
                output, errors = await asyncio.wait_for(process.communicate(), 15)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.communicate()
            assert process.returncode == 0, errors.decode()
            assert json.loads(output)["instance_revision"] == "revision-1"
            assert json.loads(output)["ids"] == ["instance-1"]
    assert json.loads(cache_files[0].read_text(encoding="utf-8"))["service"]["revision"] == "revision-1"

    live = grpc.aio.server()
    grpcapi_pb2_grpc.add_PolarisGRPCServicer_to_server(Server("revision-live"), live)
    live_port = live.add_insecure_port("127.0.0.1:0")
    assert live_port > 0
    await live.start()
    try:
        os.utime(cache_files[0], (time.time() - 120, time.time() - 120))
        for mode in ("sync", "async"):
            process = await start_child(directory, f"127.0.0.1:{live_port}", mode)
            try:
                output, errors = await asyncio.wait_for(process.communicate(), 15)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.communicate()
            assert process.returncode == 0, errors.decode()
            result = json.loads(output)
            assert result["ids"] == ["instance-1"]
            assert result["hosts"] == ["192.0.2.1"]
            assert result["instance_revision"] == "revision-live"
    finally:
        await live.stop(None)
    print(json.dumps({"abrupt_exit": True, "server_stopped": True,
                      "offline_restart_loaded": ["sync", "async"],
                      "remote_revision": "revision-live",
                      "backup_ages_seconds": [0, 120], "partial_write_ignored": True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=("seed", "sync", "async"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--address")
    args = parser.parse_args()
    if args.child:
        child(args.directory, args.address, args.child)
    else:
        with verification_directory(__file__) as directory:
            asyncio.run(verify(Path(directory)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
