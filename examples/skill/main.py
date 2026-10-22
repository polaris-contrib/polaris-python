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

"""Query and download an existing published Skill without a framework dependency."""

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO)]

from examples._internal._runtime import demo_backup_directory, demo_log_options
from polaris import Configuration, ConsumerAPI, SkillAPI, init_context_by_config
from polaris.pkg.model.service import GetInstancesRequest
from polaris.pkg.model.skill import SkillDownloadRequest, SkillGetRequest, SkillListRequest


def run(args):
    """Query metadata and fetch the requested published content and ZIP package."""
    config = Configuration()
    config.set_default()
    config.get_global().get_admin().port = 0
    config.get_global().get_api().bind_ip = "127.0.0.1"
    config.get_global().get_server_connector().addresses = args.server.split(",")
    connector = config.get_ai().get_skill().get_server_connector()
    connector.addresses = args.skill_server.split(",")
    connector.token = args.token
    root = demo_backup_directory(__file__)
    config.get_consumer().get_local_cache().persist_dir = str(root / "instances")
    connector.persist_dir = str(root / "skills")
    context = init_context_by_config(config, log_options=demo_log_options(__file__))
    try:
        api = SkillAPI(context)
        mounted_service = ""
        if args.mounted_service:
            mounted_service = args.mounted_service
            snapshot = ConsumerAPI(context).get_all_instances(GetInstancesRequest(
                namespace=args.namespace, service=mounted_service))
            content = api.get_mounted_skill(
                snapshot, skill_name=args.mounted_skill, requested_version=args.version)
            package = api.download_mounted_skill(
                snapshot, skill_name=args.mounted_skill, requested_version=args.version, format="zip")
        else:
            content = api.get_skill(SkillGetRequest(args.namespace, args.name, args.version))
            package = api.download_skill(SkillDownloadRequest(
                args.namespace, args.name, content.version.version or args.version, format="zip",
            ))
        listing = api.list_skills(SkillListRequest(namespace=args.namespace, name=args.name))
        if content.code not in (0, 200000) or package.code not in (0, 200000):
            raise RuntimeError("the requested published Skill was not found")
        result = {"name": content.resource.name, "version": content.version.version,
                  "mounted_service": mounted_service,
                  "content": content.content, "total": listing.total,
                  "zip_size": len(package.data), "loaded_from_file": content.loaded_from_file}
        print(json.dumps(result), flush=True)
        return result
    finally:
        context.destroy()


def main(argv=None):
    """Run read-only verification only with an explicit real-service opt-in."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("POLARIS_SERVER_ADDRESS", "127.0.0.1:8091"))
    parser.add_argument("--skill-server", default=os.getenv("POLARIS_SKILL_SERVER_ADDRESS", "127.0.0.1:8094"))
    parser.add_argument("--token", default=os.getenv("POLARIS_SKILL_TOKEN", os.getenv("POLARIS_TOKEN", "")))
    parser.add_argument("--namespace", default=os.getenv("POLARIS_SKILL_NAMESPACE", "default"))
    parser.add_argument("--name", default=os.getenv("POLARIS_SKILL_NAME", "lookup"))
    parser.add_argument("--version", default=os.getenv("POLARIS_SKILL_VERSION", ""))
    parser.add_argument("--mounted-service", default=os.getenv("POLARIS_MOUNTED_SERVICE", ""))
    parser.add_argument("--mounted-skill", default=os.getenv("POLARIS_MOUNTED_SKILL", ""))
    args = parser.parse_args(argv)
    if os.getenv("POLARIS_E2E") != "1":
        print("Set POLARIS_E2E=1 to run read-only Skill verification.")
        return 0
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
