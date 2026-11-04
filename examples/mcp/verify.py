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

"""Verify MCP registration, discovery, heartbeats, startup contract and shutdown."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._internal._ai_stub import AIStub
from examples._internal._runtime import verification_directory
from examples.mcp import main as demo
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection


def main():
    """Execute the real example with only the remote RPC boundary replaced."""
    stub = AIStub()
    async def fake_stub(connection, address):
        return stub
    with verification_directory(__file__), patch.object(GrpcConnection, "_stub", fake_stub), \
            patch.dict("os.environ", {"POLARIS_E2E": "1"}):
        assert demo.main(["--server", "offline:8091", "--namespace", "ns", "--service", "mcp",
                          "--host", "127.0.0.1", "--token", "token"]) == 0
        methods = [method for method, _ in stub.calls]
        assert methods.count("register") == methods.count("contract") == methods.count("deregister") == 1
        assert "heartbeat" in methods
        assert not stub.instances
        assert [item.name for item in stub.contract.service_features] == ["lookup", "document", "summarize"]
        assert all(item.status == 0 for item in stub.contract.service_features)
        print(json.dumps({"mcp": "passed", "heartbeat": methods.count("heartbeat"), "deregistered": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
