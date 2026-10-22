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

"""Strict TLS startup and actual secure specification channels."""

import asyncio
import subprocess

import grpc
import pytest
from polarismesh_specification.api.v1.service_manage import grpcapi_pb2_grpc, response_pb2, service_pb2
from polarismesh_specification.api.v1.skill_manage import skill_service_pb2 as pb, skill_service_pb2_grpc

from polaris import Configuration, ConsumerAPI, ProviderAPI, SkillAPI, init_context_by_config
from polaris.pkg.model.error import SDKError
from polaris.pkg.model.server import InstanceRegisterRequest
from polaris.pkg.model.service import GetAllInstancesRequest
from polaris.pkg.model.skill import SkillGetRequest
from polaris.plugin.server_connector.grpc_connector.tls import channel_credentials


@pytest.fixture
def certificate(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
                    "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
    return cert, key


@pytest.mark.parametrize("fields", [{"trustedCAFile": "missing.pem"}, {"certFile": "missing.pem"},
    {"keyFile": "missing.pem"}, {"trustedCAFile": 1}, {"certFile": "bad", "keyFile": "bad"}])
def test_bad_tls_configuration_refuses_context_startup(fields, monkeypatch):
    def no_plaintext(*args, **kwargs):
        raise AssertionError("TLS failure must not create a plaintext channel")

    monkeypatch.setattr(grpc.aio, "insecure_channel", no_plaintext)
    with pytest.raises(SDKError):
        config = Configuration.from_dict({"global": {"serverConnector": fields}}, apply_env=False)
        init_context_by_config(config)


def test_bad_pem_refuses_credentials(tmp_path):
    invalid = tmp_path / "invalid.pem"
    invalid.write_text("not a certificate")
    config = Configuration.from_dict({"global": {"serverConnector": {"trustedCAFile": str(invalid)}}},
                                     apply_env=False)
    with pytest.raises(SDKError, match="Invalid TLS"):
        channel_credentials(config.get_global().get_server_connector())


@pytest.mark.asyncio
@pytest.mark.parametrize("mutual", [False, True])
async def test_actual_tls_registry_and_independent_skill(mutual, certificate, tmp_path):
    cert, key = certificate
    calls = []

    class Registry(grpcapi_pb2_grpc.PolarisGRPCServicer):
        async def ReportClient(self, request, context):
            return response_pb2.Response(code={"value": 200000})

        async def RegisterInstance(self, request, context):
            calls.append(("register", context.auth_context()))
            return response_pb2.Response(code={"value": 200000}, instance=service_pb2.Instance(id={"value": "node"}))

        async def Discover(self, requests, context):
            async for request in requests:
                yield response_pb2.DiscoverResponse(code={"value": 200000}, type=1, service=request.service,
                    instances=[service_pb2.Instance(id={"value": "node"}, host={"value": "127.0.0.1"},
                        port={"value": 8080}, weight={"value": 100}, healthy={"value": True})])

    class Skill(skill_service_pb2_grpc.PolarisSkillServicer):
        async def GetSkill(self, request, context):
            calls.append(("skill", context.auth_context()))
            return pb.GetSkillResponse(code=200000, resource={"name": request.name, "namespace": request.namespace},
                                       version={"version": "v1"}, content="# skill")

    credentials = grpc.ssl_server_credentials([(key.read_bytes(), cert.read_bytes())],
        root_certificates=cert.read_bytes() if mutual else None, require_client_auth=mutual)
    servers = [grpc.aio.server(), grpc.aio.server()]
    grpcapi_pb2_grpc.add_PolarisGRPCServicer_to_server(Registry(), servers[0])
    skill_service_pb2_grpc.add_PolarisSkillServicer_to_server(Skill(), servers[1])
    ports = [server.add_secure_port("127.0.0.1:0", credentials) for server in servers]
    for server in servers:
        await server.start()
    context = None
    try:
        config = Configuration()
        config.set_default()
        config.get_global().get_api().bind_ip = "127.0.0.1"
        registry = config.get_global().get_server_connector()
        skill = config.get_ai().get_skill().get_server_connector()
        for connector, port in zip((registry, skill), ports):
            connector.addresses = [f"127.0.0.1:{port}"]
            connector.trusted_ca_file = str(cert)
            if mutual:
                connector.cert_file, connector.key_file = str(cert), str(key)
        context = init_context_by_config(config)
        response = await ProviderAPI(context).async_register(InstanceRegisterRequest(
            namespace="ns", service="svc", service_token="token", host="127.0.0.1", port=8080))
        assert response.instance_id == "node"
        nodes = await ConsumerAPI(context).async_get_all_instances(GetAllInstancesRequest(namespace="ns", service="svc"))
        assert nodes.instances[0].get_id() == "node"
        assert (await SkillAPI(context).async_get_skill(SkillGetRequest("ns", "skill", "v1"))).content == "# skill"
        assert all(auth["transport_security_type"] == [b"ssl"] for _, auth in calls)
        assert context.engine.svc_connector.connection is not context.engine.skill_connector.connection
    finally:
        if context:
            context.destroy()
        for server in servers:
            await server.stop(None)


def test_mismatched_private_key_is_rejected(certificate, tmp_path):
    cert, key = certificate
    other_key = tmp_path / "other.key"
    subprocess.run(["openssl", "genrsa", "-out", str(other_key), "2048"], check=True, capture_output=True)
    config = Configuration.from_dict({"global": {"serverConnector": {"certFile": str(cert), "keyFile": str(other_key)}}},
                                     apply_env=False)
    with pytest.raises(SDKError, match="Invalid TLS"):
        channel_credentials(config.get_global().get_server_connector())
