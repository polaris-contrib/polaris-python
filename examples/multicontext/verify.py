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

"""Verify the multi-context example in an isolated process without external connections."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2])]
from examples._internal._runtime import verification_directory

import json
import os
import subprocess
import textwrap

EXAMPLE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXAMPLE_DIR.parents[1]
OFFLINE_RUNNER = textwrap.dedent("""\
    import asyncio
    import json
    import runpy
    import sys
    import socket
    from unittest.mock import patch
    from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2
    from polaris import SDKContext

    channels, clients = [], []

    class Channel:
        def __init__(self, address):
            self.address = address
            self.owner = asyncio.get_running_loop()
            self.closed = False
            self.calls = []
            channels.append(self)

        async def close(self):
            assert asyncio.get_running_loop() is self.owner
            self.closed = True

    class Stub:
        def __init__(self, channel):
            self.channel = channel

        def record(self, method, request, metadata):
            assert asyncio.get_running_loop() is self.channel.owner
            assert not self.channel.closed
            assert dict(metadata)["x-polaris-token"] == self.channel.address.split(":")[0]
            self.channel.calls.append(method)

        async def ReportClient(self, request, timeout=None, metadata=()):
            self.record("report", request, metadata)
            assert request.id.value
            self.channel.client_id = request.id.value
            return response_pb2.Response(code={"value": 200000})

        async def RegisterInstance(self, request, timeout=None, metadata=()):
            self.record("register", request, metadata)
            assert dict(metadata)["async-regis"] == "true"
            assert request.host.value == "127.0.0.1"
            assert request.health_check.heartbeat.ttl.value == 1
            return response_pb2.Response(code={"value": 200000},
                instance=service_pb2.Instance(id={"value": self.channel.address}))

        async def DeregisterInstance(self, request, timeout=None, metadata=()):
            self.record("deregister", request, metadata)
            assert request.id.value == self.channel.address
            return response_pb2.Response(code={"value": 200000})

        async def Heartbeat(self, request, timeout=None, metadata=()):
            self.record("heartbeat", request, metadata)
            assert request.id.value == self.channel.address
            return response_pb2.Response(code={"value": 200000})

        def Discover(self, requests, timeout=None, metadata=()):
            async def responses():
                async for request in requests:
                    self.record("discover", request, metadata)
                    response = response_pb2.DiscoverResponse(code={"value": 200000}, type=request.type,
                        service=service_pb2.Service(name=request.service.name, namespace=request.service.namespace,
                            revision={"value": self.channel.address}))
                    if request.type == 1:
                        response.instances.append(service_pb2.Instance(id={"value": self.channel.address},
                            host={"value": "127.0.0.1"}, port={"value": 8080}, healthy={"value": True},
                            weight={"value": 100}))
                    yield response
            return responses()

    original_destroy = SDKContext.destroy
    async def no_tcp_connection(host, port):
        raise OSError("offline TCP boundary")

    class LocalSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def getsockname(self):
            return ("127.0.0.1", 54321)

    def fake_local_socket(address, timeout=None):
        return LocalSocket()

    def destroy(client):
        if not client.is_destroy():
            clients.append(client)
        original_destroy(client)
        engine = client.get_engine()
        assert not engine.thread.is_alive()
        assert not engine.file_cache.write_thread.is_alive()
        assert engine.file_cache.lock_file.closed
        assert engine.register_states._states == {}
        assert client.get_plugins().plugin_instance == {}
        assert client.get_plugins().event_handle_map == {}
        assert all(instance.handler.stream is None
                   for instance in client.get_value_context().logger._categories.values())
        logger = client.get_value_context().logger
        assert not logger._retention.thread.is_alive()
        assert not logger._file_locks

    sys.argv = sys.argv[1:]
    with patch("polaris.plugin.server_connector.grpc_connector.connection.grpc.aio.insecure_channel", Channel), \\
         patch("polaris.plugin.server_connector.grpc_connector.connection.grpcapi_pb2_grpc.PolarisGRPCStub", Stub), \\
         patch("polaris.pkg.model.util.asyncio.open_connection", no_tcp_connection), \\
         patch.object(socket, "create_connection", fake_local_socket), \\
         patch.object(SDKContext, "destroy", destroy):
        try:
            runpy.run_path(sys.argv[0], run_name="__main__")
        except SystemExit as error:
            if error.code != 0:
                raise
    assert len(clients) == len(channels) == 2
    assert len({channel.owner for channel in channels}) == 2
    assert len({channel.client_id for channel in channels}) == 2
    for channel in channels:
        assert channel.closed
        assert channel.calls.count("register") == channel.calls.count("deregister") == 1
        assert channel.calls.count("heartbeat") >= (1 if channel.address.startswith("first") else 2)
    for client in clients:
        other = next(item for item in clients if item is not client)
        for instance in client.get_value_context().logger._categories.values():
            assert other.get_client_id() not in instance.file_path.read_text()
    assert clients[0].get_engine().file_cache.base_dir != clients[1].get_engine().file_cache.base_dir
    print(json.dumps({"private_loops": 2, "private_channels": 2, "stopped": True,
                      "all_destroyed": all(client.is_destroy() for client in clients)}))
""")


def main() -> int:
    """Execute real lifecycle logic with only the channel/stub boundary replaced."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("POLARIS_")}
    env.update(POLARIS_E2E="1", POLARIS_FIRST_TOKEN="first", POLARIS_SECOND_TOKEN="second",
               POLARIS_FIRST_SERVICE_TOKEN="first-service-token", POLARIS_SECOND_SERVICE_TOKEN="second-service-token")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT / "src"), str(REPO_ROOT), env.get("PYTHONPATH", "")]))
    try:
        with verification_directory(__file__) as directory:
            env["POLARIS_DEMO_RUN_DIR"] = os.environ["POLARIS_DEMO_RUN_DIR"]
            env["POLARIS_DEMO_DIRECTORY"] = os.environ["POLARIS_DEMO_DIRECTORY"]
            args = [str(EXAMPLE_DIR / "main.py"), "--first-server", "first:8091", "--second-server", "second:8091",
                    "--ttl", "1", "--seconds", "1.2", "--work-dir",
                    str(Path(directory).parent / "polaris" / "backup")]
            completed = subprocess.run([sys.executable, "-c", OFFLINE_RUNNER, *args], cwd=directory,
                                       env=env, capture_output=True, text=True, timeout=20, check=False)
            (Path(directory).parent / "stdout.log").write_text(completed.stdout, encoding="utf-8")
            (Path(directory).parent / "stderr.log").write_text(completed.stderr, encoding="utf-8")
            if completed.returncode:
                raise RuntimeError(f"example failed:\n{completed.stderr}")
            result, resources = [json.loads(line) for line in completed.stdout.splitlines()]
            assert len(set(result["client_ids"])) == 2
            assert result["first_destroyed"] and result["first_api_rejected"]
            assert result["second_available_after_first_destroy"]
            assert result["initial_instances"][0][0]["id"] == "first:8091"
            assert result["initial_instances"][1][0]["id"] == "second:8091"
            assert result["second_instances_after_first_destroy"][0]["id"] == "second:8091"
            assert resources["stopped"] and resources["all_destroyed"]
            print("PASS multi-context registration, heartbeat, discovery and independent destruction")
    except (AssertionError, OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
