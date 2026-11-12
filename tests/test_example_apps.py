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

import asyncio
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


def test_example_make_commands_expand_pwd_before_make():
    for path in (REPO / "examples").rglob("README*.md"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "$PWD" in line:
                assert "ARGS='" not in line, path


def test_a2a_example_retries_transient_discovery_and_requires_current_card():
    from examples.a2a import main as example
    from polaris.pkg.model.error import ErrorCode, SDKError

    old_card = {
        "name": "agent",
        "version": "1.0.0",
        "supportedInterfaces": [{
            "url": "http://127.0.0.1:8080/a2a",
            "protocolBinding": "JSONRPC",
        }],
    }
    current_card = {**old_card, "version": "2.0.0"}
    old_text = json.dumps(old_card)
    current_text = json.dumps(current_card)

    def node(card, card_text):
        return SimpleNamespace(
            get_id=lambda: "registered-instance",
            get_metadata=lambda: {
                "ai-agent-name": card["name"],
                "ai-agent-card": card_text,
                "ai-a2a-version": "1.0",
            },
            get_version=lambda: card["version"],
            get_host=lambda: "127.0.0.1",
            get_port=lambda: 1,
            get_protocol=lambda: "",
        )

    responses = [
        SDKError(ErrorCode.ErrCodeAPITimeoutError, "temporary timeout"),
        SimpleNamespace(instances=[node(old_card, old_text)]),
        SimpleNamespace(instances=[node(current_card, current_text)]),
    ]
    calls = []

    async def discover(_request):
        calls.append("discover")
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    async def scenario():
        return await asyncio.wait_for(
            example.wait_for_registration(
                SimpleNamespace(async_get_all_instances=discover),
                namespace="ns",
                service="agent",
                instance_id="registered-instance",
                card=current_card,
                card_text=current_text,
                a2a_version="1.0",
                host="127.0.0.1",
                port=1,
                stop=asyncio.Event(),
            ),
            timeout=2,
        )

    _, discovered = asyncio.run(scenario())
    assert discovered.get_version() == "2.0.0"
    assert discovered.get_metadata()["ai-agent-card"] == current_text
    assert calls == ["discover", "discover", "discover"]


def test_a2a_example_stop_cancels_inflight_discovery():
    from examples.a2a import main as example

    async def discover(_request):
        await asyncio.sleep(3600)

    async def scenario():
        stop = asyncio.Event()
        asyncio.get_running_loop().call_later(0.01, stop.set)
        return await asyncio.wait_for(
            example.wait_for_registration(
                SimpleNamespace(async_get_all_instances=discover),
                namespace="ns",
                service="agent",
                instance_id="registered-instance",
                card={"name": "agent", "version": "1.0.0"},
                card_text="{}",
                a2a_version="1.0",
                host="127.0.0.1",
                port=1,
                stop=stop,
            ),
            timeout=1,
        )

    assert asyncio.run(scenario()) is None


def test_a2a_example_destroys_context_when_deregistration_fails(tmp_path, monkeypatch):
    from examples.a2a import main as example

    card = {
        "name": "agent",
        "version": "1.0.0",
        "supportedInterfaces": [{
            "url": "http://127.0.0.1:8080/a2a",
            "protocolBinding": "JSONRPC",
        }],
    }
    card_text = json.dumps(card)
    card_path = tmp_path / "card.json"
    card_path.write_text(card_text, encoding="utf-8")
    calls = []

    node = SimpleNamespace(
        get_id=lambda: "registered-instance",
        get_metadata=lambda: {
            "ai-agent-name": "agent",
            "ai-agent-card": card_text,
            "ai-a2a-version": "1.0",
        },
        get_version=lambda: "1.0.0",
        get_host=lambda: "127.0.0.1",
        get_port=lambda: 1,
        get_protocol=lambda: "",
    )

    async def register(_request):
        calls.append("register")
        return SimpleNamespace(instance_id="registered-instance")

    async def deregister(_request):
        calls.append("deregister")
        raise RuntimeError("deregistration failed")

    async def discover(_request):
        return SimpleNamespace(instances=[node])

    class Context:
        @staticmethod
        def destroy():
            calls.append("destroy")

    provider = SimpleNamespace(
        async_register_instance=register,
        async_deregister_instance=deregister,
    )
    consumer = SimpleNamespace(async_get_all_instances=discover)
    args = SimpleNamespace(
        card=str(card_path),
        a2a_version="1.0",
        namespace="ns",
        server="offline:8091",
        token="",
        registration_port=1,
        duration=0,
        keep_running=False,
    )

    monkeypatch.setattr(example.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(example, "demo_backup_directory", lambda *_: tmp_path)
    monkeypatch.setattr(example, "demo_log_options", lambda *_: None)
    monkeypatch.setattr(
        example, "init_context_by_config", lambda *_args, **_kwargs: Context(),
    )
    monkeypatch.setattr(example, "ProviderAPI", lambda _context: provider)
    monkeypatch.setattr(example, "ConsumerAPI", lambda _context: consumer)

    with pytest.raises(RuntimeError, match="deregistration failed"):
        asyncio.run(example.run(args))
    assert calls == ["register", "deregister", "destroy"]


def test_monitoring_example_stop_during_discovery_cleans_up(tmp_path, monkeypatch):
    from examples.monitoring import main as example

    calls = []
    handlers = {}

    async def noop(*_args, **_kwargs):
        return None

    async def register(_request):
        calls.append("register")
        return SimpleNamespace(instance_id="registered-instance")

    async def deregister(_request):
        calls.append("deregister")

    async def discover(_request):
        calls.append("discover")
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        await asyncio.sleep(3600)

    class Context:
        @staticmethod
        def destroy():
            calls.append("destroy")

    class Application:
        def __init__(self):
            self.router = SimpleNamespace(add_get=lambda *_args, **_kwargs: None)

    class Runner:
        @staticmethod
        async def setup():
            return None

        @staticmethod
        async def cleanup():
            calls.append("cleanup")

    site = SimpleNamespace(
        start=noop,
        _server=SimpleNamespace(
            sockets=[SimpleNamespace(getsockname=lambda: ("127.0.0.1", 1234))],
        ),
    )
    provider = SimpleNamespace(
        async_register_instance=register,
        async_deregister_instance=deregister,
    )
    consumer = SimpleNamespace(async_get_all_instances=discover)
    args = SimpleNamespace(
        namespace="ns",
        service="monitoring",
        token="",
        server="offline:8091",
        host="127.0.0.1",
        mode="push",
        metrics_port=0,
        push_address=[],
        push_interval=10000,
        duration=31,
        keep_running=False,
    )

    def fake_signal(signum, handler):
        if callable(handler):
            handlers[signum] = handler
            return None
        return None

    monkeypatch.setattr(example.signal, "signal", fake_signal)
    monkeypatch.setattr(example, "demo_backup_directory", lambda *_: tmp_path)
    monkeypatch.setattr(example, "demo_log_options", lambda *_: None)
    monkeypatch.setattr(
        example, "init_context_by_config", lambda *_args, **_kwargs: Context(),
    )
    monkeypatch.setattr(example, "ProviderAPI", lambda _context: provider)
    monkeypatch.setattr(example, "ConsumerAPI", lambda _context: consumer)
    monkeypatch.setattr(example.web, "Application", Application)
    monkeypatch.setattr(example.web, "AppRunner", lambda *_args, **_kwargs: Runner())
    monkeypatch.setattr(example.web, "TCPSite", lambda *_args, **_kwargs: site)

    async def scenario():
        await asyncio.wait_for(example.run(args), timeout=1)

    asyncio.run(scenario())
    assert calls == ["register", "discover", "deregister", "destroy", "cleanup"]


def test_monitoring_example_stop_during_aggregation_skips_metrics(
    tmp_path, monkeypatch,
):
    from examples.monitoring import main as example

    calls = []
    requests = []
    handlers = {}

    async def noop(*_args, **_kwargs):
        return None

    async def register(_request):
        calls.append("register")
        return SimpleNamespace(instance_id="registered-instance")

    async def deregister(_request):
        calls.append("deregister")

    async def discover(_request):
        calls.append("discover")
        node = SimpleNamespace(
            get_id=lambda: "registered-instance",
            get_host=lambda: "127.0.0.1",
            get_port=lambda: 1234,
        )
        return SimpleNamespace(instances=[node])

    async def report(_request):
        calls.append("report")
        if calls.count("report") == 3:
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            await asyncio.sleep(0)

    class Context:
        class Engine:
            class StatReporter:
                port = 12345

            stat_reporter = StatReporter()

        engine = Engine()

        @staticmethod
        def destroy():
            calls.append("destroy")

    class Application:
        def __init__(self):
            self.router = SimpleNamespace(add_get=lambda *_args, **_kwargs: None)

    class Runner:
        @staticmethod
        async def setup():
            return None

        @staticmethod
        async def cleanup():
            calls.append("cleanup")

    class Response:
        status = 200

        async def read(self):
            return b"echo"

        async def text(self):
            return ""

    class Request:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *_args):
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        @staticmethod
        def get(url):
            requests.append(url)
            return Request()

    site = SimpleNamespace(
        start=noop,
        _server=SimpleNamespace(
            sockets=[SimpleNamespace(getsockname=lambda: ("127.0.0.1", 1234))],
        ),
    )
    provider = SimpleNamespace(
        async_register_instance=register,
        async_deregister_instance=deregister,
    )
    consumer = SimpleNamespace(
        async_get_all_instances=discover,
        async_update_service_call_result=report,
    )
    args = SimpleNamespace(
        namespace="ns",
        service="monitoring",
        token="",
        server="offline:8091",
        host="127.0.0.1",
        mode="pull",
        metrics_port=0,
        push_address=[],
        push_interval=10000,
        duration=31,
        keep_running=False,
    )

    def fake_signal(signum, handler):
        if callable(handler):
            handlers[signum] = handler

    monkeypatch.setattr(example.signal, "signal", fake_signal)
    monkeypatch.setattr(example, "demo_backup_directory", lambda *_: tmp_path)
    monkeypatch.setattr(example, "demo_log_options", lambda *_: None)
    monkeypatch.setattr(
        example, "init_context_by_config", lambda *_args, **_kwargs: Context(),
    )
    monkeypatch.setattr(example, "ProviderAPI", lambda _context: provider)
    monkeypatch.setattr(example, "ConsumerAPI", lambda _context: consumer)
    monkeypatch.setattr(example.web, "Application", Application)
    monkeypatch.setattr(example.web, "AppRunner", lambda *_args, **_kwargs: Runner())
    monkeypatch.setattr(example.web, "TCPSite", lambda *_args, **_kwargs: site)
    monkeypatch.setattr(example, "ClientSession", Client)

    async def scenario():
        return await asyncio.wait_for(example.run(args), timeout=1)

    assert asyncio.run(scenario()) is None
    assert not any(url.endswith("/metric") for url in requests)
    assert calls == [
        "register", "discover", "report", "report", "report",
        "deregister", "destroy", "cleanup",
    ]


def test_monitoring_example_cleans_listener_when_context_init_fails(
    tmp_path, monkeypatch,
):
    from examples.monitoring import main as example

    calls = []

    async def noop(*_args, **_kwargs):
        return None

    def fail_init(*_args, **_kwargs):
        calls.append("init")
        raise RuntimeError("context initialization failed")

    class Application:
        def __init__(self):
            self.router = SimpleNamespace(add_get=lambda *_args, **_kwargs: None)

    class Runner:
        @staticmethod
        async def setup():
            calls.append("setup")

        @staticmethod
        async def cleanup():
            calls.append("cleanup")

    site = SimpleNamespace(
        start=noop,
        _server=SimpleNamespace(
            sockets=[SimpleNamespace(getsockname=lambda: ("127.0.0.1", 1234))],
        ),
    )
    args = SimpleNamespace(
        namespace="ns",
        service="monitoring",
        token="",
        server="offline:8091",
        host="127.0.0.1",
        mode="pull",
        metrics_port=0,
        push_address=[],
        push_interval=10000,
        duration=31,
        keep_running=False,
    )

    monkeypatch.setattr(example, "demo_backup_directory", lambda *_: tmp_path)
    monkeypatch.setattr(example, "demo_log_options", lambda *_: None)
    monkeypatch.setattr(example, "init_context_by_config", fail_init)
    monkeypatch.setattr(example.web, "Application", Application)
    monkeypatch.setattr(example.web, "AppRunner", lambda *_args, **_kwargs: Runner())
    monkeypatch.setattr(example.web, "TCPSite", lambda *_args, **_kwargs: site)

    with pytest.raises(RuntimeError, match="context initialization failed"):
        asyncio.run(asyncio.wait_for(example.run(args), timeout=1))
    assert calls == ["setup", "init", "cleanup"]


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
