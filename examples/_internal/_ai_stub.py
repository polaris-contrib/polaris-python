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

"""Fake specification RPC boundaries for the AI examples' offline verification."""

import io
import zipfile

from polarismesh_specification.api.v1.service_manage import response_pb2, service_pb2
from polarismesh_specification.api.v1.skill_manage import skill_service_pb2 as pb


class AIStub:
    """Keep fake remote state while the real SDK owns all client-side behavior."""

    def __init__(self):
        self.instances = []
        self.contract = None
        self.calls = []
        self.revision = 0
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as package:
            package.writestr("SKILL.md", "# lookup\nFind a document.")
        self.package = buffer.getvalue()

    async def ReportClient(self, request, timeout=None, metadata=()):
        return response_pb2.Response(code={"value": 200000})

    async def RegisterInstance(self, request, timeout=None, metadata=()):
        self.calls.append(("register", request))
        instance = service_pb2.Instance()
        instance.CopyFrom(request)
        instance.id.value = "mcp-node"
        self.instances = [instance]
        return response_pb2.Response(code={"value": 200000}, instance=instance)

    async def Heartbeat(self, request, timeout=None, metadata=()):
        self.calls.append(("heartbeat", request))
        return response_pb2.Response(code={"value": 200000})

    async def DeregisterInstance(self, request, timeout=None, metadata=()):
        self.calls.append(("deregister", request))
        self.instances = []
        return response_pb2.Response(code={"value": 200000})

    def Discover(self, requests, timeout=None, metadata=()):
        async def responses():
            async for request in requests:
                self.revision += 1
                yield response_pb2.DiscoverResponse(code={"value": 200000}, type=request.type,
                                                     service=service_pb2.Service(name=request.service.name,
                                                                                namespace=request.service.namespace,
                                                                                service_type=1,
                                                                                revision={"value": str(self.revision)},
                                                                                extended_metadata=[
                                                                                    {"type": 1, "agent_skill": {
                                                                                        "name": "lookup",
                                                                                        "version": "v1"}}]),
                                                     instances=self.instances)
        return responses()

    async def ReportServiceContract(self, request, timeout=None, metadata=()):
        self.calls.append(("contract", request))
        self.contract = request
        return response_pb2.Response(code={"value": 200000})

    async def GetServiceContract(self, request, timeout=None, metadata=()):
        return response_pb2.Response(code={"value": 200000}, serviceContract=self.contract)

    async def GetSkill(self, request, timeout=None, metadata=()):
        self.calls.append(("get_skill", request))
        return pb.GetSkillResponse(code=200000, content="# lookup\nFind a document.",
                                    resource={"name": request.name, "namespace": request.namespace,
                                              "tags": ["search"], "version_info": {"active_version": "v1"}},
                                    version={"name": request.name, "namespace": request.namespace,
                                             "version": request.version or "v1"})

    async def GetSkillList(self, request, timeout=None, metadata=()):
        self.calls.append(("list_skills", request))
        return pb.ListSkillsResponse(code=200000, total=1,
                                       resources=[{"name": request.name or "lookup", "namespace": request.namespace}])

    def DownloadSkill(self, request, timeout=None, metadata=()):
        self.calls.append(("download_skill", request))
        async def responses():
            if request.format == "markdown":
                yield pb.DownloadSkillResponse(code=200000, version=request.version or "v1",
                                                 content_type="text/markdown", content="# lookup\nFind a document.")
            else:
                yield pb.DownloadSkillResponse(code=200000, version=request.version or "v1",
                                                 content_type="application/zip", filename="lookup.zip",
                                                 total_size=len(self.package), zip_chunk=self.package[:30])
                yield pb.DownloadSkillResponse(code=0, zip_chunk=self.package[30:])
        return responses()
