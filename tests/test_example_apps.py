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
from urllib.parse import urlsplit

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
    shutil.copy(REPO / "examples/_python.sh", example_apps / "_python.sh")
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
    launcher = (directory / "bin").read_text(encoding="utf-8")
    assert "_python.sh" in launcher
    assert str(Path(sys.executable)) not in launcher
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


def test_mcp_example_retries_temporarily_missing_contract(
    tmp_path, monkeypatch, capsys,
):
    from examples.mcp import main as example
    from polaris.pkg.model.error import ErrorCode, SDKError, ServerCode

    calls = []
    contract_reads = 0
    registered = {}

    def register(request):
        calls.append("register")
        registered["request"] = request
        return SimpleNamespace(instance_id="registered-instance")

    def report_contract(_contract):
        calls.append("report")

    def deregister(_request):
        calls.append("deregister")

    selected = SimpleNamespace(
        get_id=lambda: "registered-instance",
        get_host=lambda: "127.0.0.1",
        get_port=lambda: 18080,
        get_protocol=lambda: "mcp-streamable-http",
        get_metadata=lambda: {"mcp-endpoint-path": "/mcp"},
    )

    def get_contract(_request):
        nonlocal contract_reads
        contract_reads += 1
        calls.append("contract")
        if contract_reads == 1:
            raise SDKError(
                ErrorCode.ErrCodeServerError,
                "not found resource",
                server_code=ServerCode.NotFoundResource,
            )
        return SimpleNamespace(service_features=[
            SimpleNamespace(name="lookup"),
            SimpleNamespace(name="document"),
            SimpleNamespace(name="summarize"),
        ])

    class Context:
        @staticmethod
        def destroy():
            calls.append("destroy")

    provider = SimpleNamespace(
        register_instance=register,
        report_service_contract=report_contract,
        deregister=deregister,
    )
    consumer = SimpleNamespace(
        get_all_instances=lambda _request: SimpleNamespace(instances=[selected]),
        get_service_contract=get_contract,
    )
    args = SimpleNamespace(
        namespace="ns",
        service="mcp",
        token="token",
        server="offline:8091",
        host="127.0.0.1",
        port=18080,
        protocol="mcp-streamable-http",
        protocol_version="2025-06-18",
        version="v1",
        path="",
        ttl=1,
        timeout=500,
        keep_running=False,
    )

    monkeypatch.setattr(example.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(example.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(example, "demo_backup_directory", lambda *_: tmp_path)
    monkeypatch.setattr(example, "demo_log_options", lambda *_: None)
    monkeypatch.setattr(example, "init_context_by_config", lambda *_args, **_kwargs: Context())
    monkeypatch.setattr(example, "ProviderAPI", lambda _context: provider)
    monkeypatch.setattr(example, "ConsumerAPI", lambda _context: consumer)

    example.run(args)

    assert calls == [
        "register", "report", "contract", "contract", "deregister", "destroy",
    ]
    assert registered["request"].protocol == "mcp-streamable-http"
    result = json.loads(capsys.readouterr().out)
    assert result["features"] == ["lookup", "document", "summarize"]


def test_mcp_example_does_not_retry_other_contract_errors(monkeypatch):
    from examples.mcp import main as example
    from polaris.pkg.model.contract import GetServiceContractRequest
    from polaris.pkg.model.error import ErrorCode, SDKError, ServerCode

    calls = []

    def get_contract(_request):
        calls.append("contract")
        raise SDKError(
            ErrorCode.ErrCodeServerError,
            "not found service",
            server_code=ServerCode.NotFoundService,
        )

    monkeypatch.setattr(example.time, "sleep", lambda _seconds: pytest.fail("must not retry"))
    request = GetServiceContractRequest("ns", "mcp", timeout=500)
    with pytest.raises(SDKError, match="not found service"):
        example.wait_for_contract(
            SimpleNamespace(get_service_contract=get_contract),
            request,
            timeout_ms=500,
        )
    assert calls == ["contract"]


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


def test_a2a_example_builds_three_interfaces_for_one_ip():
    from examples.a2a import main as example

    card = {
        "name": "agent",
        "version": "1.0.0",
        "supportedInterfaces": [],
    }
    modern = example.build_agent_card(card, "1.0", "127.0.0.1", 8080)
    assert modern["supportedInterfaces"] == [
        {
            "url": "http://127.0.0.1:8080/a2a/v1",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        },
        {
            "url": "http://127.0.0.1:8080/a2a/legacy",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "0.3",
        },
        {
            "url": "http://127.0.0.1:8080/rest",
            "protocolBinding": "HTTP+JSON",
            "protocolVersion": "1.0",
        },
    ]

    legacy = example.build_agent_card(card, "0.3", "127.0.0.1", 8080)
    assert legacy["protocolVersion"] == "0.3.0"
    assert legacy["url"] == "http://127.0.0.1:8080/a2a/legacy"
    assert legacy["additionalInterfaces"] == [
        {"url": "http://127.0.0.1:8080/a2a/v1", "transport": "JSONRPC"},
        {"url": "http://127.0.0.1:8080/rest", "transport": "HTTP+JSON"},
    ]
    assert "supportedInterfaces" not in legacy


def test_a2a_example_serves_jsonrpc_and_rest_interfaces():
    from aiohttp import ClientSession

    from examples.a2a import main as example

    card = {
        "name": "agent",
        "version": "1.0.0",
        "supportedInterfaces": [],
    }

    async def scenario():
        app, runner, port = await example.start_a2a_server("127.0.0.1", 0)
        app[example.AGENT_CARD_STATE]["card"] = example.build_agent_card(
            card, "1.0", "127.0.0.1", port)
        try:
            async with ClientSession() as client:
                response = await client.get(
                    f"http://127.0.0.1:{port}/.well-known/agent-card.json")
                assert response.status == 200
                discovered = await response.json(content_type=None)
                assert len(discovered["supportedInterfaces"]) == 3

                response = await client.post(
                    f"http://127.0.0.1:{port}/a2a/v1",
                    json={
                        "jsonrpc": "2.0",
                        "id": "v1",
                        "method": "SendMessage",
                        "params": {
                            "message": {
                                "messageId": "modern-request",
                                "contextId": "modern-context",
                                "taskId": "modern-task",
                                "role": "ROLE_USER",
                                "parts": [{"text": "modern"}],
                            },
                        },
                    },
                )
                assert response.status == 200
                modern_response = await response.json(content_type=None)
                assert modern_response["jsonrpc"] == "2.0"
                assert modern_response["id"] == "v1"
                assert set(modern_response["result"]) == {"message"}
                modern = modern_response["result"]["message"]
                assert "kind" not in modern
                assert modern["role"] == "ROLE_AGENT"
                assert modern["messageId"]
                assert modern["contextId"] == "modern-context"
                assert modern["taskId"] == "modern-task"
                assert modern["parts"][0]["text"] == (
                    "A2A 1.0 JSONRPC echo: modern")

                response = await client.post(
                    f"http://127.0.0.1:{port}/a2a/legacy",
                    json={
                        "jsonrpc": "2.0",
                        "id": "legacy",
                        "method": "message/send",
                        "params": {
                            "message": {
                                "kind": "message",
                                "messageId": "legacy-request",
                                "role": "user",
                                "parts": [{"kind": "text", "text": "old"}],
                            },
                        },
                    },
                )
                assert response.status == 200
                legacy = (await response.json(content_type=None))["result"]
                assert legacy["kind"] == "message"
                assert legacy["role"] == "agent"
                assert legacy["messageId"]
                assert legacy["parts"][0]["kind"] == "text"
                assert legacy["parts"][0]["text"] == (
                    "A2A 0.3 JSONRPC echo: old")

                rest_base = next(
                    item["url"] for item in discovered["supportedInterfaces"]
                    if item["protocolBinding"] == "HTTP+JSON"
                )
                for path in ("/message:send", "", "/v1/message:send"):
                    response = await client.post(
                        f"{rest_base}{path}",
                        json={
                            "message": {
                                "messageId": "rest-request",
                                "role": "ROLE_USER",
                                "parts": [{"text": "rest"}],
                            },
                        },
                    )
                    assert response.status == 200
                    rest_response = await response.json(content_type=None)
                    assert set(rest_response) == {"message"}
                    rest = rest_response["message"]
                    assert "kind" not in rest
                    assert rest["role"] == "ROLE_AGENT"
                    assert rest["messageId"]
                    assert rest["contextId"]
                    assert rest["parts"] == [{
                        "text": "A2A 1.0 HTTP+JSON echo: rest",
                    }]

                for path, method in (
                    ("/a2a/v1", "message/send"),
                    ("/a2a/legacy", "SendMessage"),
                ):
                    response = await client.post(
                        f"http://127.0.0.1:{port}{path}",
                        json={"jsonrpc": "2.0", "id": "wrong-version", "method": method},
                    )
                    rejected = await response.json(content_type=None)
                    assert rejected["id"] == "wrong-version"
                    assert rejected["error"]["code"] == -32601
        finally:
            await runner.cleanup()

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


def test_a2a_example_registers_card_generated_from_bound_port(
    tmp_path, monkeypatch, capsys,
):
    from examples.a2a import main as example

    calls = []
    registered = {}

    async def register(request):
        calls.append("register")
        registered["request"] = request
        return SimpleNamespace(instance_id="generated-instance")

    async def deregister(_request):
        calls.append("deregister")

    def node_for(request):
        return SimpleNamespace(
            get_id=lambda: "generated-instance",
            get_metadata=lambda: dict(request.metadata),
            get_version=lambda: request.version,
            get_host=lambda: request.host,
            get_port=lambda: request.port,
            get_protocol=lambda: request.protocol,
        )

    async def discover(_request):
        return SimpleNamespace(instances=[node_for(registered["request"])])

    class Context:
        @staticmethod
        def destroy():
            calls.append("destroy")

    provider = SimpleNamespace(
        async_register_instance=register,
        async_deregister_instance=deregister,
    )
    consumer = SimpleNamespace(async_get_all_instances=discover)
    card = {
        "name": "generated-agent",
        "version": "1.0.0",
        "supportedInterfaces": [],
    }
    card_path = tmp_path / "agent-card.json"
    card_path.write_text(json.dumps(card), encoding="utf-8")
    args = SimpleNamespace(
        card=str(card_path),
        a2a_version="1.0",
        namespace="ns",
        server="offline:8091",
        token="",
        registration_port=1,
        duration=0,
        keep_running=False,
        serve=True,
        host="127.0.0.1",
        port=0,
    )

    monkeypatch.setattr(example.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(example, "demo_backup_directory", lambda *_: tmp_path)
    monkeypatch.setattr(example, "demo_log_options", lambda *_: None)
    monkeypatch.setattr(
        example, "init_context_by_config", lambda *_args, **_kwargs: Context(),
    )
    monkeypatch.setattr(example, "ProviderAPI", lambda _context: provider)
    monkeypatch.setattr(example, "ConsumerAPI", lambda _context: consumer)

    asyncio.run(asyncio.wait_for(example.run(args), timeout=5))

    request = registered["request"]
    registered_card = json.loads(request.metadata["ai-agent-card"])
    interfaces = registered_card["supportedInterfaces"]
    assert len(interfaces) == 3
    assert {urlsplit(item["url"]).path for item in interfaces} == {
        "/a2a/v1", "/a2a/legacy", "/rest",
    }
    listen_port = urlsplit(interfaces[0]["url"]).port
    assert all(f":{listen_port}/" in item["url"] for item in interfaces)
    assert request.host == "127.0.0.1"
    assert request.port == 1
    assert request.protocol == ""
    assert calls == ["register", "deregister", "destroy"]

    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert output["listen_port"] == listen_port
    assert set(output["endpoints"].values()) == {item["url"] for item in interfaces}


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
