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

"""Verify A2A registration metadata, discovery and explicit shutdown offline."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._internal._ai_stub import AIStub
from examples._internal._runtime import verification_directory
from examples.a2a import main as demo
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection


def main():
    stub = AIStub()
    async def fake_stub(connection, address):
        return stub
    with verification_directory(__file__), patch.object(GrpcConnection, "_stub", fake_stub), \
            patch.dict("os.environ", {"POLARIS_E2E": "1"}):
        assert demo.main(["--server", "offline:8091", "--namespace", "ns", "--token", "token",
                          "--duration", "5.2"]) == 0
        methods = [method for method, _ in stub.calls]
        assert methods.count("register") == methods.count("deregister") == 1
        assert "heartbeat" in methods and not stub.instances
        request = stub.calls[0][1]
        assert request.metadata["a2a.transport"] == "JSONRPC"
        assert request.metadata["a2a.path"] == "/a2a"
        assert json.loads(request.metadata["a2a.agent.card"])["name"] == request.metadata["ai-agent-name"]
        print(json.dumps({"a2a": "passed", "heartbeat": methods.count("heartbeat"), "deregistered": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
