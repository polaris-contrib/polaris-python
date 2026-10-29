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

"""Execute the snapshot workflow's version scripts without publishing packages."""

import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/python-snapshot.yaml"


def workflow():
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def run_version_step(tmp_path, configured, job, step_id, run_number="42"):
    about = tmp_path / "src/polaris/_version.py"
    about.parent.mkdir(parents=True, exist_ok=True)
    original = f'# Preserve the header.\n__version__ = "{configured}"\nOTHER = "unchanged"\n'
    about.write_text(original, encoding="utf-8")
    output = tmp_path / "github-output"
    step = next(step for step in workflow()["jobs"][job]["steps"]
                if step.get("id") == step_id)
    lines = step["run"].splitlines()
    assert lines[0].endswith("<<'PY'") and lines[-1] == "PY"
    completed = subprocess.run(
        [sys.executable, "-c", "\n".join(lines[1:-1])],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_OUTPUT": str(output), "GITHUB_RUN_NUMBER": run_number},
        capture_output=True,
        text=True,
        timeout=10,
    )
    emitted = output.read_text(encoding="utf-8") if output.exists() else ""
    return completed, about, original, emitted


def test_snapshot_publish_only_uses_verified_artifacts():
    config = workflow()
    assert config["on"]["push"]["branches"] == ["main", "release/*", "develop"]
    assert "workflow_dispatch" in config["on"]
    assert "pull_request" not in config["on"]
    jobs = config["jobs"]
    assert "refs/heads/develop" in jobs["check-snapshot"]["if"]
    assert "refs/heads/main" in jobs["check-snapshot"]["if"]
    assert "refs/heads/release/" in jobs["check-snapshot"]["if"]
    assert jobs["build"]["needs"] == "check-snapshot"
    assert jobs["build"]["if"] == "${{ needs.check-snapshot.outputs.IS_SNAPSHOT == 'true' }}"
    assert jobs["publish"]["needs"] == "build"
    assert jobs["publish"]["environment"] == "Release"
    upload = jobs["build"]["steps"][-1]
    download, publish = jobs["publish"]["steps"]
    assert upload["with"]["name"] == download["with"]["name"]
    assert publish["with"]["password"] == "${{ secrets.PYPI_API_TOKEN }}"
    assert publish["with"]["skip-existing"] == "true"


@pytest.mark.parametrize("configured, expected", [
    ("0.2.0", False),
    ("0.2.1a1", False),
    ("0.2.1rc1", False),
    ("0.2.0.post1", False),
    ("0.2.1.dev0", True),
    ("0.2.1a2.dev7", True),
])
def test_snapshot_gate(tmp_path, configured, expected):
    completed, about, original, emitted = run_version_step(
        tmp_path, configured, "check-snapshot", "check_version")
    assert completed.returncode == 0, completed.stderr
    assert emitted == f"IS_SNAPSHOT={str(expected).lower()}\n"
    assert about.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("configured, expected", [
    ("0.2.1.dev0", "0.2.1.dev42"),
    ("0.2.1.dev999", "0.2.1.dev42"),
    ("0.2.1a2.dev7", "0.2.1a2.dev42"),
    ("1!0.2.1.dev0", "1!0.2.1.dev42"),
])
def test_snapshot_version_preserves_target_and_header(tmp_path, configured, expected):
    completed, about, original, emitted = run_version_step(
        tmp_path, configured, "build", "version")
    assert completed.returncode == 0, completed.stderr
    assert emitted == f"VERSION={expected}\n"
    assert runpy.run_path(str(about))["__version__"] == expected
    assert about.read_text(encoding="utf-8") == original.replace(configured, expected)


@pytest.mark.parametrize("configured", ["0.2.0", "0.2.1a1", "0.2.1.dev0+local", "invalid"])
def test_snapshot_set_version_rejects_nonpublic_development_version(tmp_path, configured):
    completed, about, original, emitted = run_version_step(
        tmp_path, configured, "build", "version")
    assert completed.returncode != 0
    assert emitted == ""
    assert about.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("run_number", ["0", "-1", "invalid"])
def test_snapshot_set_version_rejects_invalid_run_number(tmp_path, run_number):
    completed, about, original, emitted = run_version_step(
        tmp_path, "0.2.1.dev0", "build", "version", run_number)
    assert completed.returncode != 0
    assert emitted == ""
    assert about.read_text(encoding="utf-8") == original


def test_snapshot_gate_rejects_local_version(tmp_path):
    completed, about, original, emitted = run_version_step(
        tmp_path, "0.2.1.dev0+local", "check-snapshot", "check_version")
    assert completed.returncode != 0
    assert emitted == ""
    assert about.read_text(encoding="utf-8") == original


def test_snapshot_rerun_keeps_version(tmp_path):
    first = run_version_step(tmp_path / "first", "0.2.1.dev0", "build", "version")
    rerun = run_version_step(tmp_path / "rerun", "0.2.1.dev0", "build", "version")
    next_run = run_version_step(tmp_path / "next", "0.2.1.dev0", "build", "version", "43")
    assert first[0].returncode == rerun[0].returncode == next_run[0].returncode == 0
    assert first[3] == rerun[3] == "VERSION=0.2.1.dev42\n"
    assert next_run[3] == "VERSION=0.2.1.dev43\n"
