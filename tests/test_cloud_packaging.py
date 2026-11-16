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

"""Tests for the cloud E2E deployment and log transfer scripts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="cloud packaging scripts require a POSIX shell",
)

REPO = Path(__file__).resolve().parents[1]
CLOUD = REPO / "integration" / "cloud"


@pytest.mark.parametrize(
    "script",
    ["build-package.sh", "run-e2e.sh", "pack-logs.sh", "import-logs.sh"],
)
def test_cloud_scripts_expose_help(script):
    result = subprocess.run(
        ["bash", CLOUD / script, "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout or "usage:" in result.stdout


def test_cloud_package_contains_runtime_entrypoints_without_logs(tmp_path):
    output = tmp_path / "dist"
    build = tmp_path / "build"
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = str(tmp_path / "uv-cache")
    wheel = tmp_path / "polaris_python-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as package:
        package.writestr("polaris/__init__.py", "")
    result = subprocess.run(
        [
            "bash",
            CLOUD / "build-package.sh",
            "--without-runtime",
            "--output-dir",
            output,
            "--build-root",
            build,
            "--name",
            "polaris-python-cloud-test",
            "--wheel",
            wheel,
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    archive = output / "polaris-python-cloud-test.tar.gz"
    assert archive.is_file()
    assert (output / "polaris-python-cloud-test.tar.gz.sha256").is_file()

    with tarfile.open(archive, "r:gz") as package:
        names = package.getnames()
        manifest_member = package.extractfile(
            "polaris-python-cloud-test/manifest.json"
        )
        assert manifest_member is not None
        manifest = json.loads(manifest_member.read())

    required = {
        "polaris-python-cloud-test/run-e2e.sh",
        "polaris-python-cloud-test/pack-logs.sh",
        "polaris-python-cloud-test/import-logs.sh",
        "polaris-python-cloud-test/summarize-results.py",
        "polaris-python-cloud-test/examples/README-zh.md",
        "polaris-python-cloud-test/integration/verify_e2e.sh",
    }
    assert required.issubset(names)
    assert manifest["runtime_bundled"] is False
    assert not any(
        "/.logs/" in name
        or "/.runtime/" in name
        or "/__pycache__/" in name
        for name in names
    )


def test_cloud_log_pack_and_local_import(tmp_path):
    run = tmp_path / "cloud-runs" / "run-20261116_120000-1"
    summary_dir = run / "logs" / "verify-e2e-summary-test"
    summary_dir.mkdir(parents=True)
    (run / "manifest.json").write_text(
        json.dumps({
            "run_id": "run-20261116_120000-1",
            "package": "polaris-python-cloud-test",
            "server": "127.0.0.1:8091",
            "namespace": "polaris-python-integration",
            "started_at": "2026-11-16T12:00:00Z",
            "finished_at": "2026-11-16T12:01:00Z",
            "exit_code": 0,
        }),
        encoding="utf-8",
    )
    (run / "run.log").write_text("PASS quickstart\n", encoding="utf-8")
    (summary_dir / "summary.json").write_text(
        json.dumps({
            "passed": 1,
            "failed": 0,
            "results": [{"scenario": "quickstart", "code": 0}],
        }),
        encoding="utf-8",
    )

    archive = tmp_path / "returned-logs.tar.gz"
    packed = subprocess.run(
        [
            "bash",
            CLOUD / "pack-logs.sh",
            "--run-dir",
            run,
            "--output",
            archive,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert packed.returncode == 0, packed.stderr
    assert archive.is_file()
    assert Path(f"{archive}.sha256").is_file()
    assert (run / "analysis.txt").is_file()

    imported = tmp_path / "imported"
    imported_result = subprocess.run(
        [
            "bash",
            CLOUD / "import-logs.sh",
            archive,
            "--output-dir",
            imported,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert imported_result.returncode == 0, imported_result.stderr
    analysis = imported / run.name / "analysis.txt"
    assert analysis.is_file()
    text = analysis.read_text(encoding="utf-8")
    assert "1 passed, 0 failed" in text
    assert "quickstart" in text
