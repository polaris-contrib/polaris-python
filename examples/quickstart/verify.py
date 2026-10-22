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

"""Verify the synchronous quickstart example without a Polaris server."""

from __future__ import annotations

import sys
from pathlib import Path
from contextlib import ExitStack

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2])]
from examples._internal._runtime import verification_directory

import atexit
import json
import os
import select
import socket
import subprocess
import textwrap
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

EXAMPLE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXAMPLE_DIR.parents[1]

OFFLINE_RUNNER = textwrap.dedent("""\
    import atexit
    import json
    import os
    import runpy
    import sys
    import socket
    from unittest.mock import patch
    from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2

    calls = []

    class Stub:
        async def ReportClient(self, request, timeout=None, metadata=()):
            calls.append("report")
            return response_pb2.Response(code={"value": 200000})

        async def RegisterInstance(self, request, timeout=None, metadata=()):
            calls.append("register")
            assert request.service_token.value == "service-token"
            assert request.host.value == "127.0.0.1"
            assert request.health_check.heartbeat.ttl.value == 1
            return response_pb2.Response(
                code={"value": 200000},
                instance=service_pb2.Instance(id={"value": "quickstart-provider"}),
            )

        async def Heartbeat(self, request, timeout=None, metadata=()):
            calls.append("heartbeat")
            assert request.id.value == "quickstart-provider"
            return response_pb2.Response(code={"value": 200000})

        async def DeregisterInstance(self, request, timeout=None, metadata=()):
            calls.append("deregister")
            assert request.id.value == "quickstart-provider"
            return response_pb2.Response(code={"value": 200000})

        def Discover(self, requests, timeout=None, metadata=()):
            async def responses():
                async for request in requests:
                    calls.append("discover")
                    response = response_pb2.DiscoverResponse(
                        code={"value": 200000}, type=request.type,
                        service=service_pb2.Service(
                            name=request.service.name, namespace=request.service.namespace,
                            revision={"value": "quickstart-revision"},
                        ),
                    )
                    if request.type == 1:
                        response.instances.append(service_pb2.Instance(
                            id={"value": "quickstart-provider"},
                            service=request.service.name, namespace=request.service.namespace,
                            host={"value": "127.0.0.1"}, port={"value": int(os.environ["QUICKSTART_PROVIDER_PORT"])},
                            healthy={"value": True}, weight={"value": 100},
                        ))
                    yield response
            return responses()

    stub = Stub()

    async def fake_stub(self, address):
        return stub

    class LocalSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def getsockname(self):
            return ("127.0.0.1", 54321)

    original_create_connection = socket.create_connection

    def fake_local_socket(address, *args, **kwargs):
        if address == ("127.0.0.1", 8091):
            return LocalSocket()
        return original_create_connection(address, *args, **kwargs)

    class ProbeWriter:
        def get_extra_info(self, name):
            assert name == "sockname"
            return ("127.0.0.1", 54321)

        def close(self):
            pass

        async def wait_closed(self):
            pass

    async def fake_probe_connection(host, port):
        return None, ProbeWriter()

    def report_calls():
        print(json.dumps({"offline_calls": calls}), flush=True)

    atexit.register(report_calls)
    sys.argv = sys.argv[1:]
    with patch("polaris.plugin.server_connector.grpc_connector.connection.GrpcConnection._stub", fake_stub), \\
         patch.object(socket, "create_connection", fake_local_socket), \\
         patch("polaris.pkg.model.util.asyncio.open_connection", fake_probe_connection):
        try:
            runpy.run_path(sys.argv[0], run_name="__main__")
        except SystemExit as error:
            if error.code not in (None, 0):
                raise
""")


def read_json_line(process: subprocess.Popen, expected_key: str, timeout: float = 10) -> dict:
    while True:
        ready, _, _ = select.select([process.stdout], [], [], timeout)
        if not ready:
            raise RuntimeError(f"process did not print {expected_key} JSON: {process.args}")
        line = process.stdout.readline()
        if not line:
            stderr = process.stderr.read() if process.stderr else ""
            raise RuntimeError(f"process exited before {expected_key} JSON: {stderr}")
        process.demo_lines.append(line)
        value = json.loads(line)
        if expected_key in value:
            return value


def start_process(script: Path, arguments: list[str], directory: Path, extra_env: dict[str, str]):
    env = {key: value for key, value in os.environ.items() if not key.startswith("POLARIS_")}
    env.update(
        POLARIS_SERVER_ADDRESS="127.0.0.1:8091",
        POLARIS_TOKEN="access-token",
        POLARIS_LOG_LEVEL="ERROR",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=os.pathsep.join(filter(None, [str(REPO_ROOT / "src"), str(REPO_ROOT), env.get("PYTHONPATH", "")])),
        **extra_env,
    )
    env["POLARIS_DEMO_RUN_DIR"] = str(directory.parent.parent)
    env["POLARIS_DEMO_DIRECTORY"] = os.environ["POLARIS_DEMO_DIRECTORY"]
    process = subprocess.Popen(
        [sys.executable, "-c", OFFLINE_RUNNER, str(script), *arguments],
        cwd=directory, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    process.demo_directory = directory
    process.demo_lines = []
    return process


def ensure_stopped(process):
    """Reap even a child whose startup or verification fails."""
    if process.poll() is None:
        process.terminate()
        try:
            output, errors = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            output, errors = process.communicate(timeout=5)
        (process.demo_directory / "stdout.log").write_text("".join(process.demo_lines) + output, encoding="utf-8")
        (process.demo_directory / "stderr.log").write_text(errors, encoding="utf-8")


def stop(process: subprocess.Popen) -> dict:
    process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
    (process.demo_directory / "stdout.log").write_text("".join(process.demo_lines) + stdout, encoding="utf-8")
    (process.demo_directory / "stderr.log").write_text(stderr, encoding="utf-8")
    if process.returncode != 0:
        raise RuntimeError(f"process exited with {process.returncode}:\n{stderr}")
    return json.loads(stdout.splitlines()[-1])


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    with verification_directory(__file__) as directory, ExitStack() as children:
        root = Path(directory)
        provider_dir = root / "provider"
        consumer_dir = root / "consumer"
        provider_dir.mkdir()
        consumer_dir.mkdir()
        consumer_port = free_port()

        provider = start_process(
            EXAMPLE_DIR / "provider" / "main.py",
            ["--namespace", "ns", "--service", "svc", "--service-token", "service-token",
             "--port", "0", "--ttl", "1"],
            provider_dir, {"QUICKSTART_PROVIDER_PORT": "0"},
        )
        children.callback(ensure_stopped, provider)
        provider_startup = read_json_line(provider, "registered")
        provider_port = provider_startup["port"]
        # The demo registers with a one-second TTL; keep it alive through one heartbeat.
        time.sleep(1.2)

        consumer = start_process(
            EXAMPLE_DIR / "consumer" / "main.py",
            ["--namespace", "ns", "--service", "svc", "--port", str(consumer_port)],
            consumer_dir, {"QUICKSTART_PROVIDER_PORT": str(provider_port)},
        )
        children.callback(ensure_stopped, consumer)
        consumer_startup = read_json_line(consumer, "started")
        assert consumer_startup["listen"] == f"0.0.0.0:{consumer_port}"

        try:
            with urlopen(f"http://127.0.0.1:{consumer_port}/echo", timeout=5) as response:
                body = response.read().decode()
                assert response.status == 200
                assert body == f"Hello, I'm svc Provider, My host : 127.0.0.1:{provider_port}"

            request = Request(
                f"http://127.0.0.1:{consumer_port}/echo-with-body",
                data=json.dumps({"namespace": "ns", "service": "svc"}).encode(),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urlopen(request, timeout=5) as response:
                assert response.status == 200
                assert response.read().decode() == body
        except HTTPError as error:
            raise RuntimeError(f"consumer returned HTTP {error.code}: {error.read().decode()}") from error
        finally:
            provider_result = stop(provider)
            consumer_result = stop(consumer)

        assert "register" in provider_result["offline_calls"]
        assert "heartbeat" in provider_result["offline_calls"]
        assert "deregister" in provider_result["offline_calls"]
        assert "report" in consumer_result["offline_calls"]
        assert "discover" in consumer_result["offline_calls"]
        print("PASS synchronous quickstart registration, discovery, call, and cleanup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
