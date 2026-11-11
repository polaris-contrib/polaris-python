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

"""Small runtime helpers shared by user-facing examples."""

import os
import socket
from pathlib import Path


def get_local_host(server_address):
    """Return the local TCP source IP used to reach a Polaris server."""
    from polaris.pkg.model.util import get_ip_from_int_with_port

    host, port = get_ip_from_int_with_port(server_address)
    with socket.create_connection((host, port), timeout=2) as connection:
        return connection.getsockname()[0]


getLocalHost = get_local_host


def demo_polaris_directory(entry):
    """Return the per-run polaris directory containing log and backup trees."""
    run = os.getenv("POLARIS_DEMO_RUN_DIR")
    if run:
        return Path(run) / "polaris"
    return Path(entry).resolve().parent / ".logs" / "manual" / "polaris"


def demo_log_options(entry, *, level=None, component=None):
    """Build context log options without coupling the example to the E2E runner."""
    from polaris.api.log import LogOptions

    path = demo_polaris_directory(entry) / "log"
    if component:
        path /= component
    return LogOptions(level=level, log_dir=path)


def demo_backup_directory(entry, *, component=None):
    """Return the inspectable backup directory for a demo run."""
    path = demo_polaris_directory(entry) / "backup"
    if component:
        path /= component
    path.mkdir(parents=True, exist_ok=True)
    return path
