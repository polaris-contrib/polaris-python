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

"""Exercise manual example launchers independently from integration verification."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from examples import _apps as apps

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def example_apps(tmp_path, monkeypatch):
    root = tmp_path / "examples"
    root.mkdir()
    shutil.copy(REPO / "examples/_apps.py", root / "_apps.py")
    for name in ("sdkconfig/code", "sdkconfig/file"):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "main.py").write_text("print('demo')\n", encoding="utf-8")
    monkeypatch.setattr(apps, "EXAMPLES", root)
    monkeypatch.setattr(apps, "REPO", tmp_path)
    return root


def test_example_apps_cli_prints_usage_from_another_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO / "examples/_apps.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def test_examples_do_not_offer_verification_entries():
    for name in ("_run.py", "_scripts.sh", "run.sh", "logs.sh", "cleanup.sh"):
        assert not (REPO / "examples" / name).exists()
    assert not (REPO / "examples/verify.sh").exists()
    assert not (REPO / "examples/verify_e2e.sh").exists()
    assert not list((REPO / "examples").rglob("verify.py"))
    for name in ("Makefile", "demo.mk", "group.mk"):
        text = (REPO / "examples" / name).read_text(encoding="utf-8")
        assert "verify" not in text
        assert "integration" not in text
    text = (REPO / "examples/_apps.py").read_text(encoding="utf-8")
    assert "from integration" not in text
    assert "import integration" not in text


def test_example_selection_supports_groups_and_scoped_cleanup(example_apps):
    code = example_apps / "sdkconfig/code"
    file = example_apps / "sdkconfig/file"
    hidden = code / ".logs/run-1/work"
    hidden.mkdir(parents=True)
    (hidden / "main.py").touch()
    assert apps.selected_directories(example_apps, "sdkconfig,sdkconfig/code") == [code, file]
    assert apps.selected_directories(example_apps / "sdkconfig", "code") == [code]
    with pytest.raises(ValueError, match="inside examples"):
        apps.selected_directories(example_apps, "../")
    with pytest.raises(ValueError, match="nonempty"):
        apps.selected_directories(example_apps, ",")
    with pytest.raises(ValueError, match="application entry point"):
        apps.run(example_apps / "sdkconfig", [])


def test_example_run_preserves_arguments_cwd_logs_and_exit_status(example_apps):
    directory = example_apps / "sdkconfig/code"
    (directory / "polaris.yaml").write_text("example config", encoding="utf-8")
    (directory / "main.py").write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "print(json.dumps({'arguments': sys.argv[1:], 'cwd': os.getcwd(), "
        "'config': Path('polaris.yaml').read_text()}))\n"
        "print('diagnostic output', file=sys.stderr)\n"
        "raise SystemExit(7)\n", encoding="utf-8",
    )
    assert apps.run(directory, ["--value", "two words"]) == 7
    run = next((directory / ".logs").glob("run-*"))
    output = (run / "console.log").read_text(encoding="utf-8")
    value = next(json.loads(line) for line in output.splitlines() if line.startswith("{"))
    assert value == {
        "arguments": ["--value", "two words"], "cwd": str(directory), "config": "example config",
    }
    assert "diagnostic output" in output
    assert json.loads((run / "result.json").read_text())["exit_code"] == 7
    assert not apps.owned_processes([directory])
    assert apps.cleanup(
        [directory], SimpleNamespace(force=True, dry_run=False, keep_logs=True),
    ) == 0
    assert not (directory / ".runtime").exists()
    assert not (example_apps.parent / "integration").exists()


def test_example_makefile_launcher_and_group_commands(example_apps):
    make = shutil.which("make")
    if make is None:
        pytest.skip("Make is unavailable")
    shutil.copy(REPO / "examples/demo.mk", example_apps / "demo.mk")
    shutil.copy(REPO / "examples/group.mk", example_apps / "group.mk")
    (example_apps.parent / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    directory = example_apps / "sdkconfig/code"
    (directory / "Makefile").write_text("include ../../demo.mk\n", encoding="utf-8")
    group = example_apps / "sdkconfig"
    (group / "Makefile").write_text("SUBDIRS := code file\ninclude ../group.mk\n", encoding="utf-8")
    env = {**os.environ, "POLARIS_PYTHON": sys.executable}

    def execute(scope, *arguments):
        result = subprocess.run(
            [make, "-C", str(scope), *arguments], env=env,
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    assert "demo" in execute(directory, "run", "ARGS=--value 'two words'")
    assert "demo" in execute(group, "run", "DEMO=code")
    assert "console.log" in execute(directory, "logs", "ARGS=--latest --tail 1")
    assert "Dry run" in execute(group, "cleanup", "ARGS=--only code --dry-run")
    assert (directory / "bin").exists()
    assert "Removed" in execute(directory, "cleanup", "ARGS=--force --keep-logs")
    assert list((directory / ".logs").glob("run-*/console.log"))
    assert not (directory / ".runtime").exists()


@pytest.mark.parametrize("name", [".logs", ".runtime"])
def test_example_run_rejects_artifact_symlinks_before_start(example_apps, tmp_path, name):
    directory = example_apps / "sdkconfig/code"
    external = tmp_path / "external"
    external.mkdir()
    (directory / name).symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="must not be a symlink"):
        apps.run(directory, [])
    assert list(external.iterdir()) == []


def test_example_cleanup_previews_and_preserves_source_and_integration(example_apps, capsys):
    selected = example_apps / "sdkconfig/code"
    other = example_apps / "sdkconfig/file"
    integration_logs = example_apps.parent / "integration/.logs/sdkconfig/code"
    integration_logs.mkdir(parents=True)
    (integration_logs / "console.log").write_text("integration", encoding="utf-8")
    for directory in (selected, other):
        for name in (".logs", ".runtime", ".build"):
            (directory / name).mkdir()
            (directory / name / "sentinel").write_text("local", encoding="utf-8")
        (directory / "bin").write_text("launcher", encoding="utf-8")
        (directory / "polaris.yaml").write_text("config", encoding="utf-8")
    args = SimpleNamespace(force=True, dry_run=True, keep_logs=False)
    assert apps.cleanup([selected], args) == 0
    assert "Dry run" in capsys.readouterr().out
    assert (selected / ".logs/sentinel").exists()
    args.dry_run = False
    assert apps.cleanup([selected], args) == 0
    assert not (selected / ".logs").exists()
    assert not (selected / ".runtime").exists()
    assert not (selected / ".build").exists()
    assert not (selected / "bin").exists()
    assert (selected / "main.py").exists()
    assert (selected / "polaris.yaml").read_text() == "config"
    assert (other / ".logs/sentinel").exists()
    assert (integration_logs / "console.log").read_text() == "integration"


def test_example_cleanup_requires_confirmation(example_apps, monkeypatch):
    directory = example_apps / "sdkconfig/code"
    (directory / ".logs").mkdir()
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert apps.cleanup([directory], SimpleNamespace(force=False, dry_run=False, keep_logs=False)) == 0
    assert (directory / ".logs").exists()


def test_example_cleanup_unlinks_artifact_symlinks_without_following(example_apps, tmp_path):
    directory = example_apps / "sdkconfig/code"
    external = tmp_path / "external"
    external.mkdir()
    (external / "keep.log").write_text("external", encoding="utf-8")
    for name in (".logs", ".runtime", ".build", "bin"):
        (directory / name).symlink_to(external, target_is_directory=True)
    assert apps.log_files([directory]) == []
    assert apps.cleanup([directory], SimpleNamespace(force=True, dry_run=False, keep_logs=False)) == 0
    assert (external / "keep.log").read_text() == "external"


def test_example_logs_select_latest_category_only(example_apps):
    directory = example_apps / "sdkconfig/code"
    for name, stamp in (("run-old", 100), ("run-new", 200)):
        run = directory / ".logs" / name
        for category in ("base", "cache"):
            path = run / "polaris/log" / category / f"{category}.log"
            path.parent.mkdir(parents=True)
            path.write_text(category, encoding="utf-8")
        (run / "console.log").write_text("console", encoding="utf-8")
        os.utime(run, (stamp, stamp))
    files = apps.log_files([directory], latest=True, category="cache")
    assert files == [directory / ".logs/run-new/polaris/log/cache/cache.log"]


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("example process did not become ready")


def start_example(root, name):
    directory = root / name
    (directory / "main.py").write_text(
        "import signal, sys, time\n"
        "def stop(*_):\n"
        "    print('graceful shutdown', flush=True)\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "print('ready', flush=True)\n"
        "while True: time.sleep(0.1)\n", encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, str(root / "_apps.py"), "run", name],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        wait_for(lambda: any(
            "ready" in path.read_text(encoding="utf-8")
            for path in (directory / ".logs").glob("run-*/console.log")
        ))
    except BaseException:
        process.terminate()
        process.communicate(timeout=5)
        raise
    return process


@pytest.mark.skipif(os.name == "nt", reason="Windows does not deliver SIGTERM to Python handlers")
def test_example_cleanup_stops_only_owned_processes_and_keeps_logs(example_apps):
    first = start_example(example_apps, "sdkconfig/code")
    second = start_example(example_apps, "sdkconfig/file")
    directory = example_apps / "sdkconfig/code"
    records = directory / ".runtime/processes"
    stale = {
        "kind": "example", "pid": second.pid, "created": 0,
        "command": psutil.Process(second.pid).cmdline(), "entry": str(directory / "main.py"),
    }
    (records / f"{second.pid}.json").write_text(json.dumps(stale), encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, str(example_apps / "_apps.py"), "cleanup",
             "--only", "sdkconfig/code", "--force", "--keep-logs"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, result.stderr
        first.communicate(timeout=5)
        assert first.poll() is not None
        assert second.poll() is None
        assert not (directory / ".runtime").exists()
        output = next((directory / ".logs").glob("run-*/console.log")).read_text()
        assert "graceful shutdown" in output
        assert list((directory / ".logs").glob("run-*/result.json"))
        assert (example_apps / "sdkconfig/file/.runtime").exists()
    finally:
        for process in (first, second):
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)


@pytest.mark.skipif(os.name == "nt", reason="Windows does not deliver SIGTERM to Python handlers")
def test_example_interrupt_escalates_and_retains_result(example_apps, monkeypatch):
    directory = example_apps / "sdkconfig/code"
    (directory / "main.py").write_text(
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "os.kill(os.getppid(), signal.SIGTERM)\n"
        "time.sleep(30)\n", encoding="utf-8",
    )
    monkeypatch.setattr(apps, "TERMINATE_GRACE_SECONDS", 0.1)
    assert apps.run(directory, []) == 128 + signal.SIGTERM
    result = json.loads(next((directory / ".logs").glob("run-*/result.json")).read_text())
    assert result["interrupted"] == signal.SIGTERM
    assert result["exit_code"] == -signal.SIGKILL
    assert not apps.owned_processes([directory])
    assert apps.cleanup(
        [directory], SimpleNamespace(force=True, dry_run=False, keep_logs=True),
    ) == 0
    assert not (directory / ".runtime").exists()
