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

REPO = Path(__file__).resolve()
while not (REPO / "pyproject.toml").exists():
    REPO = REPO.parent
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from integration._ai_stub import AIStub
from integration._runtime import verification_directory
from integration.fixtures import a2a as demo
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures"
from polarismesh_specification.api.v1.service_manage import service_pb2


BASE_ARGS = [
    "--server", "offline:8091",
    "--namespace", "ns",
    "--token", "token",
]


class PeerInstanceAIStub(AIStub):
    """Expose a valid peer returned before the instance created by this run."""

    def __init__(self, peer_card_text):
        super().__init__()
        self.peer_card_text = peer_card_text

    async def RegisterInstance(self, request, timeout=None, metadata=()):
        response = await super().RegisterInstance(request, timeout=timeout, metadata=metadata)
        current = self.instances[0]
        current.weight.value = 0
        peer = service_pb2.Instance()
        peer.CopyFrom(current)
        peer.id.value = "peer-agent-node"
        peer.port.value = 18080
        peer.version.value = "2.0.0"
        peer.weight.value = 100
        peer.metadata["ai-agent-card"] = self.peer_card_text
        self.instances.append(peer)
        return response


def run_demo(current, extra_args=(), duration="0", stub_factory=AIStub):
    stub = stub_factory()
    current["stub"] = stub
    assert demo.main([
        *BASE_ARGS,
        "--duration", duration,
        *extra_args,
    ]) == 0
    return stub


def expect_failure(current, extra_args, message):
    stub = AIStub()
    current["stub"] = stub
    try:
        demo.main([*BASE_ARGS, "--duration", "0", *extra_args])
    except ValueError as error:
        assert message in str(error)
    else:
        raise AssertionError(f"expected AgentCard validation failure containing {message!r}")
    assert stub.calls == []
    return stub


def assert_registration(stub, card_text, *, port, a2a_version, instance_version):
    methods = [method for method, _ in stub.calls]
    assert methods.count("register") == methods.count("deregister") == 1
    assert not stub.instances
    request = next(request for method, request in stub.calls if method == "register")
    assert set(request.metadata) == {"ai-agent-name", "ai-agent-card", "ai-a2a-version"}
    assert request.metadata["ai-agent-card"] == card_text
    assert request.metadata["ai-a2a-version"] == a2a_version
    card = json.loads(card_text)
    assert request.metadata["ai-agent-name"] == card["name"]
    assert request.host.value == "127.0.0.1"
    assert request.port.value == port
    assert request.protocol.value == ""
    assert request.version.value == instance_version
    deregister = next(request for method, request in stub.calls if method == "deregister")
    assert deregister.host.value == "127.0.0.1"
    assert deregister.port.value == port


def main():
    current = {}

    async def fake_stub(connection, address):
        return current["stub"]

    with verification_directory(__file__) as work, \
            patch.object(GrpcConnection, "_stub", fake_stub), \
            patch.dict("os.environ", {"POLARIS_E2E": "1"}):
        card_path = FIXTURE_DIR / "config" / "a2a" / "agent-card.json"
        card_text = card_path.read_text(encoding="utf-8")
        default_stub = run_demo(current, duration="5.2")
        assert_registration(
            default_stub, card_text, port=1, a2a_version="1.0", instance_version="1.0.0")
        methods = [method for method, _ in default_stub.calls]
        assert "heartbeat" in methods

        custom_port_stub = run_demo(current, ["--registration-port", "18080"])
        assert_registration(
            custom_port_stub, card_text, port=18080, a2a_version="1.0", instance_version="1.0.0")

        multi_ip = dict(json.loads(card_text))
        multi_ip["supportedInterfaces"] = [
            {"url": "http://127.0.0.1:8080/a2a", "protocolBinding": "JSONRPC"},
            {"url": "http://127.0.0.2:8080/a2a", "protocolBinding": "JSONRPC"},
        ]
        multi_ip_path = work / "agent-card-multi-ip.json"
        multi_ip_path.write_text(json.dumps(multi_ip), encoding="utf-8")
        expect_failure(current, ["--card", str(multi_ip_path)], "same IP")
        expect_failure(
            current, ["--a2a-version", "0.3", "--card", str(card_path)],
            "1.0 field supportedInterfaces")

        mixed_1_0 = json.loads(card_text)
        mixed_1_0.update({
            "protocolVersion": "0.3.0",
            "url": "http://127.0.0.2:8080/a2a",
            "preferredTransport": "JSONRPC",
        })
        mixed_1_0_path = work / "agent-card-mixed-1.0.json"
        mixed_1_0_path.write_text(json.dumps(mixed_1_0), encoding="utf-8")
        expect_failure(current, ["--card", str(mixed_1_0_path)], "0.3 schema fields")

        legacy = {
            "protocolVersion": "0.3.0",
            "name": "legacy-document-agent",
            "version": "0.9.0",
            "url": "http://127.0.0.1:8080/a2a",
            "preferredTransport": "JSONRPC",
            "additionalInterfaces": [
                {"url": "http://127.0.0.1:9090/grpc", "transport": "GRPC"},
            ],
        }
        legacy_text = json.dumps(legacy)
        mixed_0_3 = dict(legacy)
        mixed_0_3["supportedInterfaces"] = json.loads(card_text)["supportedInterfaces"]
        mixed_0_3_path = work / "agent-card-mixed-0.3.json"
        mixed_0_3_path.write_text(json.dumps(mixed_0_3), encoding="utf-8")
        expect_failure(
            current, ["--a2a-version", "0.3", "--card", str(mixed_0_3_path)],
            "1.0 field supportedInterfaces")

        optional_legacy = dict(legacy)
        optional_legacy.pop("preferredTransport")
        optional_legacy["additionalInterfaces"] = None
        optional_legacy_text = json.dumps(optional_legacy)
        optional_legacy_path = work / "agent-card-0.3-optional-fields.json"
        optional_legacy_path.write_text(optional_legacy_text, encoding="utf-8")
        optional_legacy_stub = run_demo(
            current, ["--a2a-version", "0.3", "--card", str(optional_legacy_path)])
        assert_registration(
            optional_legacy_stub, optional_legacy_text, port=1, a2a_version="0.3",
            instance_version="0.9.0")

        legacy_path = work / "agent-card-0.3.json"
        legacy_path.write_text(legacy_text, encoding="utf-8")
        legacy_stub = run_demo(
            current, ["--a2a-version", "0.3", "--card", str(legacy_path)])
        assert_registration(
            legacy_stub, legacy_text, port=1, a2a_version="0.3", instance_version="0.9.0")

        peer_card = json.loads(card_text)
        peer_card["version"] = "2.0.0"
        peer_card["supportedInterfaces"] = [{
            "url": "http://127.0.0.1:18080/a2a",
            "protocolBinding": "JSONRPC",
        }]
        peer_card_text = json.dumps(peer_card)
        peer_stub = run_demo(
            current, stub_factory=lambda: PeerInstanceAIStub(peer_card_text))
        assert_registration(
            peer_stub, card_text, port=1, a2a_version="1.0", instance_version="1.0.0")

        for invalid_port in ("0", "65536"):
            stub = AIStub()
            current["stub"] = stub
            try:
                demo.main([*BASE_ARGS, "--registration-port", invalid_port])
            except SystemExit as error:
                assert error.code == 2
            else:
                raise AssertionError("invalid registration port must fail before RPC")
            assert stub.calls == []

        print(json.dumps({
            "a2a": "passed",
            "heartbeat": methods.count("heartbeat"),
            "registration_ports": [1, 18080],
            "schema_versions": ["0.3", "1.0"],
            "multiple_instances": True,
            "deregistered": True,
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
