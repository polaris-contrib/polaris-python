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

"""Keep default SDK runtime files in pytest's per-test temporary directories."""

import pytest

from polaris.api import log
from polaris.pkg.config import stat_reporter
from polaris.plugin.stat_reporter.prometheus import PrometheusReporter


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """Exercise real relative defaults without writing into the source checkout."""
    monkeypatch.chdir(tmp_path)
    # Multiple SDK contexts can coexist in one test process; use ephemeral metrics ports.
    original_start = PrometheusReporter.start

    async def isolated_start(reporter, engine):
        admin = reporter.global_config.get_admin()
        original_port = admin.port
        if original_port == stat_reporter.DEFAULT_ADMIN_PORT:
            admin.port = 0
        try:
            return await original_start(reporter, engine)
        finally:
            admin.port = original_port

    monkeypatch.setattr(PrometheusReporter, "start", isolated_start)
    monkeypatch.setattr(log, "default_logger", None)
    monkeypatch.setattr(log, "_process_loggers", {})
    monkeypatch.setattr(log, "_process_log_paths", {})
    monkeypatch.setattr(log, "_process_rotation", (50 * 1024 * 1024, 5, 30))
    try:
        yield tmp_path
    finally:
        log._close_process_logs()
