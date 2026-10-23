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

"""Verify working-directory independence, retained logs and cleanup ownership."""

import json
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from examples._internal import _manage as manager, _runtime as runtime
from examples._internal._real_verify import cache_backup_glob, e2e_namespace, service_name

REPO = Path(__file__).resolve().parents[1]


def test_real_service_name_uses_the_full_demo_path():
    before = datetime.now().strftime("%Y%m%d%H%M%S")
    name = service_name("cache/restart")
    after = datetime.now().strftime("%Y%m%d%H%M%S")
    label, suffix = name.rsplit("-", 1)
    assert label == "polaris-python-e2e-cache-restart"
    assert len(suffix) == 17 and suffix.isdigit()
    assert before <= suffix[:14] <= after
    assert service_name("loadbalancer/wr").startswith("polaris-python-e2e-loadbalancer-wr-")
    assert service_name("quickstart").startswith("polaris-python-e2e-quickstart-")


def test_real_verification_registers_into_python_integration(monkeypatch):
    monkeypatch.delenv("POLARIS_E2E_NAMESPACE", raising=False)
    assert e2e_namespace() == "python-integration"
    monkeypatch.setenv("POLARIS_E2E_NAMESPACE", "custom")
    assert e2e_namespace() == "custom"


@pytest.mark.parametrize("name", ["mcp", "skill", "a2a", "monitoring", "events"])
def test_ai_example_default_does_not_create_context_or_connect(monkeypatch, name):
    import importlib
    example = importlib.import_module(f"examples.{name}.main")
    monkeypatch.delenv("POLARIS_E2E", raising=False)

    def unexpected_context(*args, **kwargs):
        raise AssertionError("default example must not create an SDK context")

    monkeypatch.setattr(example, "init_context_by_config", unexpected_context)
    assert example.main([]) == 0


def test_multicontext_verifier_checks_post_exit_cleanup(tmp_path, monkeypatch):
    from examples.multicontext import verify

    run = tmp_path / "run"
    monkeypatch.setenv("POLARIS_DEMO_RUN_DIR", str(run))
    monkeypatch.setenv("POLARIS_DEMO_DIRECTORY", str(tmp_path / "demo"))
    monkeypatch.setattr(runtime, "_tracked", set())
    assert verify.main() == 0
    startup, shutdown = [json.loads(line) for line in (run / "stdout.log").read_text().splitlines()]
    assert startup["second_available_after_first_destroy"]
    assert "all_destroyed" not in startup
    assert shutdown["stopped"] and shutdown["all_destroyed"]


@pytest.mark.parametrize("relative_path, calls", [
    ("skill/main.py", ("api.get_skill(", "api.list_skills(", "api.download_skill(")),
    ("mcp/main.py", ("provider.register_instance(", "consumer.get_all_instances(",
                     "consumer.get_one_instance(", "consumer.get_service_contract(")),
    ("cache/expiry/main.py", ("consumer.get_instances(",)),
    ("cache/restart/verify.py", ("consumer.get_instances(",)),
    ("sdkconfig/code/main.py", ("consumer.get_instances(",)),
    ("sdkconfig/file/main.py", ("consumer.get_instances(",)),
    ("multicontext/main.py", ("sync_discover(", "consumer.get_instances(")),
    ("events/main.py", ("consumer.get_instances(", "get_event_center().register_listener(")),
])
def test_demo_default_or_verifier_paths_cover_synchronous_apis(relative_path, calls):
    source = (REPO / "examples" / relative_path).read_text(encoding="utf-8")
    for call in calls:
        assert call in source, f"{relative_path} does not call {call}"


def test_restart_backup_glob_matches_svc_cache_files(tmp_path):
    service = "polaris-python-e2e-cache-restart-53e071ea"
    (tmp_path / f"svc#default#{service}#instance.json").write_text("{}", encoding="utf-8")
    assert any(tmp_path.glob(cache_backup_glob("default", service)))


@pytest.mark.parametrize("name", sorted(set(manager.VERIFIERS) | set(manager.GROUPS)))
def test_scenario_documentation_describes_verification(name):
    directory = REPO / "examples" / name
    documentation = directory / "test.md"
    assert documentation.is_file()
    documentation_text = documentation.read_text(encoding="utf-8")
    assert len(documentation_text) > 1000
    assert "脚本作用" in documentation_text
    assert "验证" in documentation_text
    assert "执行产物与解读" in documentation_text
    for artifact in ("console.log", "result.json", "verification.log"):
        assert artifact in documentation_text
    assert "注册服务与实例" in documentation_text
    assert "端口" in documentation_text
    assert "离线验证" in documentation_text
    assert "远端验证" in documentation_text
    assert "verify_e2e.sh" in documentation_text
    assert "POLARIS_SERVER_ADDRESS" in documentation_text
    assert "POLARIS_SERVICE_TOKEN" in documentation_text
    if name:
        assert not list(directory.glob("*.sh"))


@pytest.mark.parametrize("script", ["verify.sh", "verify_e2e.sh", "logs.sh", "cleanup.sh"])
def test_root_example_scripts_print_usage(script):
    path = REPO / "examples" / script
    assert os.access(path, os.X_OK)
    result = subprocess.run([str(path), "--help"], cwd=REPO,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


@pytest.fixture
def example_tree(monkeypatch, tmp_path):
    root = tmp_path / "examples"
    monkeypatch.setattr(manager, "EXAMPLES", root)
    monkeypatch.setattr(manager, "REPO", tmp_path)
    for name in ("sdkconfig", "sdkconfig/code", "sdkconfig/file"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def test_cleanup_preview_and_removal_are_scoped_to_selected_demo(example_tree, capsys):
    selected = example_tree / "sdkconfig/code"
    other = example_tree / "sdkconfig/file"
    for directory in (selected, other):
        (directory / ".logs").mkdir()
        (directory / ".logs/console.log").write_text("retained")
        (directory / "polaris.yaml").write_text("keep YAML")
    manager.cleanup(selected, SimpleNamespace(force=True, dry_run=True))
    assert "Dry run" in capsys.readouterr().out
    assert (selected / ".logs/console.log").exists()
    manager.cleanup(selected, SimpleNamespace(force=True, dry_run=False))
    assert not (selected / ".logs").exists()
    assert (selected / "polaris.yaml").read_text() == "keep YAML"
    assert (other / ".logs/console.log").read_text() == "retained"


def test_cleanup_keep_logs_stops_processes_but_preserves_logs(example_tree):
    selected = example_tree / "sdkconfig/code"
    logs = selected / ".logs"
    logs.mkdir()
    (logs / "console.log").write_text("keep me", encoding="utf-8")
    code = ("import time; from examples._internal._runtime import track_process; "
            f"track_process({str(selected)!r}, {str(selected / 'main.py')!r}); "
            "print('ready', flush=True); time.sleep(30)")
    process = subprocess.Popen([sys.executable, "-c", code], cwd=REPO,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert process.stdout.readline() == "ready\n"
    try:
        manager.cleanup(selected, SimpleNamespace(force=True, dry_run=False, keep_logs=True))
        process.wait(timeout=5)
        assert not psutil.pid_exists(process.pid)
        assert (logs / "console.log").read_text(encoding="utf-8") == "keep me"
        assert (selected / ".runtime").exists()
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=5)


def test_cleanup_delete_services_targets_only_e2e_services(monkeypatch):
    calls = []

    class Response:
        def __init__(self, body):
            self.body = body

        def read(self):
            return json.dumps(self.body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    def fake_urlopen(request, timeout=None):
        calls.append(request)
        if len(calls) == 1:
            body = {
                "code": 200000,
                "services": [
                    {"namespace": "python-integration", "name": "polaris-python-e2e-quickstart-1"},
                    {"namespace": "python-integration", "name": "polaris-python-e2e-mcp-2"},
                    {"namespace": "python-integration", "name": "business-service"},
                    {"namespace": "other", "name": "polaris-python-e2e-not-selected"},
                ],
            }
        else:
            body = {"code": 200000, "responses": [{"code": 200000}]}
        return Response(body)

    monkeypatch.setattr(manager.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("POLARIS_SERVER_ADDRESS", "1.2.3.4:8091")
    monkeypatch.setenv("POLARIS_SERVICE_TOKEN", "service-token")
    address, namespace, names = manager.test_services()
    assert address == "http://1.2.3.4:8090"
    assert namespace == "python-integration"
    assert names == ["polaris-python-e2e-quickstart-1", "polaris-python-e2e-mcp-2"]

    assert manager.delete_test_services(address, namespace, names) == names
    assert calls[1].full_url == f"{address}/naming/v1/services/delete"
    assert calls[1].method == "POST"
    assert calls[1].headers["Content-type"] == "application/json"
    assert calls[1].headers["X-polaris-token"] == "service-token"
    assert json.loads(calls[1].data) == [
        {"namespace": namespace, "name": name} for name in names
    ]


def test_cleanup_does_not_follow_runtime_or_log_symlinks(example_tree, tmp_path):
    selected = example_tree / "sdkconfig/code"
    external = tmp_path / "external"
    external.mkdir()
    (external / "keep.log").write_text("external data")
    (selected / ".logs").symlink_to(external, target_is_directory=True)
    (selected / ".runtime").symlink_to(external, target_is_directory=True)
    assert manager.log_files(selected) == []
    manager.cleanup(selected, SimpleNamespace(force=True, dry_run=False))
    assert (external / "keep.log").read_text() == "external data"


def test_category_log_filter_does_not_match_the_demo_directory(example_tree, monkeypatch, capsys):
    monkeypatch.setitem(manager.VERIFIERS, "circuitbreaker", ("unused.py", []))
    selected = example_tree / "circuitbreaker"
    run = selected / ".logs/verify-1"
    for category in ("base", "circuitbreaker"):
        path = run / "polaris" / "log" / category / f"polaris-{category}.log"
        path.parent.mkdir(parents=True)
        path.write_text(category)
    manager.show_logs(selected, SimpleNamespace(category="circuitbreaker", latest=True, follow=False, tail=1))
    output = capsys.readouterr().out
    assert "polaris-circuitbreaker.log" in output
    assert "polaris-base.log" not in output


def test_verification_retains_output_on_failure_and_restores_environment(tmp_path, monkeypatch):
    entry = tmp_path / "demo/verify.py"
    entry.parent.mkdir()
    entry.touch()
    monkeypatch.delenv("POLARIS_DEMO_RUN_DIR", raising=False)
    monkeypatch.delenv("POLARIS_DEMO_DIRECTORY", raising=False)
    monkeypatch.setattr(runtime, "_tracked", set())
    with pytest.raises(RuntimeError, match="failed verification"):
        with runtime.verification_directory(entry) as directory:
            directory.joinpath("cache").mkdir()
            print("inspect this failure")
            raise RuntimeError("failed verification")
    logs = list(entry.parent.glob(".logs/*/verification.log"))
    assert len(logs) == 1
    assert "inspect this failure" in logs[0].read_text()
    assert (logs[0].parent / "work/cache").is_dir()
    assert "POLARIS_DEMO_RUN_DIR" not in os.environ
    assert "POLARIS_DEMO_DIRECTORY" not in os.environ


def test_demo_backups_are_siblings_under_polaris_directory(tmp_path, monkeypatch):
    entry = tmp_path / "demo/main.py"
    entry.parent.mkdir()
    entry.touch()
    run = tmp_path / "run"
    monkeypatch.setenv("POLARIS_DEMO_RUN_DIR", str(run))
    monkeypatch.setenv("POLARIS_DEMO_DIRECTORY", str(entry.parent))
    monkeypatch.setattr(runtime, "_tracked", set())
    options = runtime.demo_log_options(entry, component="consumer")
    backup = runtime.demo_backup_directory(entry, component="consumer")
    assert Path(options.log_dir) == run / "polaris" / "log" / "consumer"
    assert backup == run / "polaris" / "backup" / "consumer"
    assert backup.parent.parent == Path(options.log_dir).parent.parent == run / "polaris"
    monkeypatch.delenv("POLARIS_DEMO_RUN_DIR")
    assert runtime.demo_backup_directory(entry, component="consumer") == (
        entry.parent / ".logs" / "manual" / "polaris" / "backup" / "consumer"
    )


def test_cleanup_stops_owned_process_and_keeps_other_demo_alive(example_tree):
    owned, other = example_tree / "sdkconfig/code", example_tree / "sdkconfig/file"

    def start(directory):
        code = ("import time; from examples._internal._runtime import track_process; "
                f"track_process({str(directory)!r}, {str(directory / 'main.py')!r}); "
                "print('ready', flush=True); time.sleep(30)")
        process = subprocess.Popen([sys.executable, "-c", code], cwd=REPO,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert process.stdout.readline() == "ready\n"
        return process

    first, second = start(owned), start(other)
    try:
        # Simulate an old record with a PID reused by the other demo.
        record = owned / ".runtime/processes" / f"{second.pid}.json"
        record.write_text(json.dumps({"pid": second.pid, "created": 0,
                                     "command": psutil.Process(second.pid).cmdline(),
                                     "entry": str(owned / "main.py")}))
        manager.cleanup(owned, SimpleNamespace(force=True, dry_run=False))
        first.wait(timeout=5)
        assert not psutil.pid_exists(first.pid)
        assert second.poll() is None
        assert (other / ".runtime").exists()
    finally:
        for process in (first, second):
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)


def test_group_selection_runs_each_demo_once():
    assert manager.verification_targets("", "sdkconfig,cache") == [
        "sdkconfig/code", "sdkconfig/file", "cache/expiry", "cache/restart"]
    assert manager.verification_targets("loadbalancer", None) == [
        "loadbalancer/random", "loadbalancer/wr"]
    assert manager.verification_targets("loadbalancer", None, groups=manager.REAL_GROUPS) == [
        "loadbalancer/random", "loadbalancer/wr"]
    assert manager.verification_targets("", "servicerouter") == ["servicerouter"]
    assert manager.verification_targets("", "mcp,skill,mcp") == ["mcp", "skill"]
    assert manager.verification_targets("sdkconfig", "code,code") == ["sdkconfig/code"]
    with pytest.raises(ValueError, match="Unknown demo"):
        manager.verification_targets("sdkconfig", "missing")


def test_verification_timeout_reaps_a_quiet_process_and_retains_failure(example_tree, monkeypatch):
    selected = example_tree / "sdkconfig/code"
    entry = selected / "verify.py"
    entry.write_text("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)")
    monkeypatch.setattr(manager, "TERMINATE_GRACE_SECONDS", 0.1)
    assert manager.run_process(selected, entry, [], "verify", 0.2) == 124
    result = next(selected.glob(".logs/*/result.json"))
    assert json.loads(result.read_text())["timed_out"] is True
    assert result.with_name("console.log").exists()


def test_interrupted_verification_retains_result_even_when_child_exits_cleanly(example_tree):
    selected = example_tree / "sdkconfig/code"
    entry = selected / "verify.py"
    entry.write_text(
        "import os, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "os.kill(os.getppid(), signal.SIGTERM)\n"
        "time.sleep(30)\n"
    )
    assert manager.run_process(selected, entry, [], "verify", 5) == 128 + signal.SIGTERM
    result = json.loads(next(selected.glob(".logs/*/result.json")).read_text())
    assert result["exit_code"] == 0
    assert result["interrupted"] == signal.SIGTERM


def test_interrupted_group_does_not_start_remaining_demos(example_tree, monkeypatch):
    calls = []
    monkeypatch.setattr(manager, "track_process", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["_manage.py", "--directory", str(example_tree / "sdkconfig"), "verify"])

    def interrupt(directory, *args):
        calls.append(directory)
        return 128 + signal.SIGINT

    monkeypatch.setattr(manager, "run_process", interrupt)
    assert manager.main() == 128 + signal.SIGINT
    assert calls == [example_tree / "sdkconfig/code"]
