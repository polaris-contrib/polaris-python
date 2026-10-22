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

"""Verify Skill queries, ZIP assembly and network fallback in a new context."""

import io
import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._internal._ai_stub import AIStub
from examples._internal._runtime import demo_backup_directory, demo_log_options, verification_directory
from examples.skill import main as demo
from polaris import Configuration, ConsumerAPI, SkillAPI, init_context_by_config
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.pkg.model.service import GetInstancesRequest
from polaris.pkg.model.skill import SkillListRequest
from polaris.plugin.server_connector.grpc_connector.connection import GrpcConnection


def main():
    """Use valid ZIP bytes and the real atomic backup writer."""
    stub = AIStub()
    async def fake_stub(connection, address):
        return stub
    with verification_directory(__file__), patch.object(GrpcConnection, "_stub", fake_stub), \
            patch.dict("os.environ", {"POLARIS_E2E": "1"}):
        assert demo.main(["--skill-server", "offline:8094", "--namespace", "ns", "--name", "lookup",
                          "--mounted-service", "agent"]) == 0
        config = Configuration()
        config.set_default()
        config.get_global().get_admin().port = 0
        config.get_global().get_api().bind_ip = "127.0.0.1"
        root = demo_backup_directory(__file__)
        config.get_consumer().get_local_cache().persist_dir = str(root / "instances")
        config.get_ai().get_skill().get_server_connector().persist_dir = str(root / "skills")
        context = init_context_by_config(config, log_options=demo_log_options(__file__, component="offline-restart"))
        async def unavailable(*args, **kwargs):
            raise SDKError(ErrorCode.ErrCodeNetworkError, "offline")
        with patch.object(context.engine.skill_connector, "get_skill", unavailable), \
                patch.object(context.engine.skill_connector, "download_skill", unavailable), \
                patch.object(context.engine.skill_connector, "list_skills", unavailable):
            try:
                api = SkillAPI(context)
                snapshot = ConsumerAPI(context).get_all_instances(GetInstancesRequest(
                    namespace="ns", service="agent"))
                content = api.get_mounted_skill(snapshot)
                package = api.download_mounted_skill(snapshot, format="zip")
                assert content.loaded_from_file and content.version.version == "v1"
                assert package.loaded_from_file
                with zipfile.ZipFile(io.BytesIO(package.data)) as archive:
                    assert archive.read("SKILL.md").decode() == content.content
                try:
                    api.list_skills(SkillListRequest())
                except SDKError as error:
                    assert error.err_code == ErrorCode.ErrCodeNetworkError
                else:
                    raise AssertionError("list_skills must remain remote-only")
            finally:
                context.destroy()
        assert not context.engine.thread.is_alive()
        assert not context.engine.skill_flow.persistence.write_thread.is_alive()
        print(json.dumps({"skill": "passed", "mounted_service": "agent", "zip_size": len(package.data),
                          "restart_fallback": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
