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

import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from integration import _manage as manager, _runtime as runtime
from integration._real_verify import (
    E2E_SKILL_FIXTURE_NAME,
    cache_backup_glob,
    default_skill_address,
    e2e_namespace,
    required_environment,
    resolve_skill_namespace,
    scenario_environment,
    service_name,
)
from integration._support import configure_e2e_event_reporting, get_local_host
from integration import _support as support
from polaris import Configuration

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
    monkeypatch.setenv("POLARIS_E2E_NAMESPACE", "default")
    with pytest.raises(ValueError, match="must not be default"):
        e2e_namespace()
    with pytest.raises(ValueError, match="must not be default"):
        manager.e2e_namespace()


def test_real_verification_service_token_is_optional(monkeypatch):
    monkeypatch.setenv("POLARIS_SERVER_ADDRESS", "127.0.0.1:8091")
    monkeypatch.delenv("POLARIS_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("POLARIS_E2E_SERVICE_TOKEN", raising=False)
    assert required_environment() == ("127.0.0.1:8091", "")

    monkeypatch.setenv("POLARIS_SERVICE_TOKEN", "service-token")
    assert required_environment() == ("127.0.0.1:8091", "service-token")

    monkeypatch.setenv("POLARIS_E2E_SERVICE_TOKEN", "e2e-token")
    assert required_environment() == ("127.0.0.1:8091", "e2e-token")


def test_skill_address_is_derived_from_registry_host():
    assert default_skill_address("127.0.0.1:8091") == "127.0.0.1:8094"
    assert default_skill_address("[2001:db8::1]:8091") == "[2001:db8::1]:8094"
    assert E2E_SKILL_FIXTURE_NAME == "polaris-python-e2e-skill-fixture"


def test_skill_namespace_defaults_to_isolated_namespace_for_auto_discovery():
    assert resolve_skill_namespace("python-integration") == "python-integration"
    assert resolve_skill_namespace("python-integration", configured_name="published") == "default"
    assert resolve_skill_namespace(
        "python-integration", configured_name="published", configured_namespace="custom",
    ) == "custom"
    assert resolve_skill_namespace(
        "python-integration", configured_namespace="custom",
    ) == "custom"


def test_real_verification_event_reporter_uses_pushgateway(monkeypatch):
    monkeypatch.setenv("POLARIS_E2E", "1")
    monkeypatch.setenv("POLARIS_EVENT_REPORTER_ADDRESS", "127.0.0.1:9091")
    monkeypatch.setenv("POLARIS_EVENT_REPORTER_PUSH_INTERVAL", "250")
    config = Configuration()
    config.set_default()
    configure_e2e_event_reporting(config)
    reporter = config.get_global().get_event_reporter()
    pushgateway = reporter.get_pushgateway()
    assert reporter.enable is True
    assert reporter.chain == ["pushgateway"]
    assert pushgateway.address == ["127.0.0.1:9091"]
    assert pushgateway.push_interval == 250
    connector = config.get_global().get_server_connector()
    assert connector.get_connect_timeout() == 5000
    assert connector.get_message_timeout() == 15000
    assert config.get_global().get_api().get_timeout() == 15000


def test_real_verification_timeouts_can_be_overridden(monkeypatch):
    monkeypatch.setenv("POLARIS_E2E", "1")
    monkeypatch.setenv("POLARIS_E2E_CONNECT_TIMEOUT_MS", "6000")
    monkeypatch.setenv("POLARIS_E2E_MESSAGE_TIMEOUT_MS", "16000")
    monkeypatch.setenv("POLARIS_E2E_API_TIMEOUT_MS", "17000")
    monkeypatch.setenv("POLARIS_E2E_SKILL_TIMEOUT_MS", "31000")
    monkeypatch.setenv("POLARIS_E2E_SKILL_DOWNLOAD_TIMEOUT_MS", "62000")
    config = Configuration()
    config.set_default()
    configure_e2e_event_reporting(config)
    connector = config.get_global().get_server_connector()
    assert connector.get_connect_timeout() == 6000
    assert connector.get_message_timeout() == 16000
    assert config.get_global().get_api().get_timeout() == 17000
    skill_connector = config.get_ai().get_skill().get_server_connector()
    assert skill_connector.message_timeout == 31000
    assert skill_connector.download_timeout == 62000

    env = scenario_environment("registry:8091")
    assert env["POLARIS_E2E_CONNECT_TIMEOUT_MS"] == "6000"
    assert env["POLARIS_E2E_MESSAGE_TIMEOUT_MS"] == "16000"
    assert env["POLARIS_E2E_API_TIMEOUT_MS"] == "17000"
    assert env["POLARIS_E2E_SKILL_TIMEOUT_MS"] == "31000"
    assert env["POLARIS_E2E_SKILL_DOWNLOAD_TIMEOUT_MS"] == "62000"


@pytest.mark.parametrize("name", ["sdkconfig/file", "sdkconfig/code"])
def test_real_verification_discovery_cli_timeout_uses_scenario_environment(name, monkeypatch):
    from integration import _real_verify as real

    recorded = {}

    def with_provider(_name, _namespace, _env, _address, _token, effect):
        return effect("service", {"instance_id": "registered-instance"})

    def run_demo(_script, arguments, _env, timeout):
        recorded["arguments"] = arguments
        recorded["timeout"] = timeout
        return json.dumps({
            "discovery": {"instances": [{"id": "registered-instance"}]},
        })

    monkeypatch.setattr(real, "with_provider", with_provider)
    monkeypatch.setattr(real, "run_demo", run_demo)

    real.verify_discovery_demo(
        name, {"POLARIS_E2E_API_TIMEOUT_MS": "120000"},
        "registry:8091", "", "ns",
    )

    timeout_index = recorded["arguments"].index("--timeout") + 1
    assert recorded["arguments"][timeout_index] == "120000"
    assert recorded["timeout"] == 135


def test_real_verification_mcp_cli_timeout_uses_scenario_environment(monkeypatch):
    from integration import _real_verify as real

    recorded = {}

    def start_demo(_script, arguments, _env, _expected_key, **_kwargs):
        recorded["arguments"] = arguments
        recorded["timeout"] = _kwargs.get("timeout")
        raise RuntimeError("stop after recording arguments")

    monkeypatch.setattr(real, "start_demo", start_demo)
    monkeypatch.setattr(real, "free_port", lambda: 18080)

    with pytest.raises(RuntimeError, match="stop after recording arguments"):
        real.run_scenario(
            "mcp", "registry:8091", "", "ns",
            {"POLARIS_E2E_API_TIMEOUT_MS": "120000"},
        )

    timeout_index = recorded["arguments"].index("--timeout") + 1
    assert recorded["arguments"][timeout_index] == "120000"
    assert recorded["timeout"] == 135


def test_real_verification_startup_budget_covers_api_timeout_and_outer_budget():
    from integration import _real_verify as real

    assert real.scenario_operation_timeout({
        "POLARIS_E2E_API_TIMEOUT_MS": "120000",
        "POLARIS_E2E_SCENARIO_TIMEOUT_SECONDS": "600",
    }, 90) == 135
    assert real.scenario_operation_timeout({
        "POLARIS_E2E_API_TIMEOUT_MS": "120000",
        "POLARIS_E2E_SCENARIO_TIMEOUT_SECONDS": "100",
    }, 90) == 100


def test_real_verification_uses_outer_timeout_for_bounded_startup(monkeypatch):
    from integration import _real_verify as real

    recorded = {}

    class StopAfterStart(Exception):
        pass

    def start_demo(*_args, **kwargs):
        recorded.update(kwargs)
        raise StopAfterStart

    monkeypatch.setattr(real, "start_demo", start_demo)
    env = {"POLARIS_E2E_SCENARIO_TIMEOUT_SECONDS": "600"}

    with pytest.raises(StopAfterStart):
        real.verify_lossless(env, "registry:8091", "", "ns")

    assert recorded["timeout"] == 600


def test_skill_preflight_uses_scenario_environment_timeouts(monkeypatch, tmp_path):
    from integration import _real_verify as real

    recorded = {}

    def init_context(config, **_kwargs):
        connector = config.get_global().get_server_connector()
        skill_connector = config.get_ai().get_skill().get_server_connector()
        recorded.update(
            connect_timeout=connector.connect_timeout,
            message_timeout=connector.message_time,
            api_timeout=config.get_global().get_api().timeout,
            skill_message_timeout=skill_connector.message_timeout,
            skill_download_timeout=skill_connector.download_timeout,
        )
        return SimpleNamespace(destroy=lambda: recorded.setdefault("destroyed", True))

    monkeypatch.delenv("POLARIS_E2E", raising=False)
    monkeypatch.setattr(real, "init_context_by_config", init_context)
    monkeypatch.setattr(
        real,
        "SkillAPI",
        lambda _context: SimpleNamespace(
            list_skills=lambda _request: SimpleNamespace(resources=[]),
        ),
    )
    env = {
        "POLARIS_E2E": "1",
        "POLARIS_E2E_CONNECT_TIMEOUT_MS": "6000",
        "POLARIS_E2E_MESSAGE_TIMEOUT_MS": "16000",
        "POLARIS_E2E_API_TIMEOUT_MS": "17000",
        "POLARIS_E2E_SKILL_TIMEOUT_MS": "31000",
        "POLARIS_E2E_SKILL_DOWNLOAD_TIMEOUT_MS": "62000",
        "POLARIS_DEMO_RUN_DIR": str(tmp_path),
    }

    assert real.discover_skill_name(
        env, "registry:8091", "skill:8094", "ns", timeout=0,
    ) is None
    assert recorded == {
        "connect_timeout": 6000,
        "message_timeout": 16000,
        "api_timeout": 17000,
        "skill_message_timeout": 31000,
        "skill_download_timeout": 62000,
        "destroyed": True,
    }


def test_parent_provider_probe_uses_scenario_environment_overrides(monkeypatch, tmp_path):
    from integration import _real_verify as real

    recorded = {}

    async def get_instances(request):
        recorded["request_timeout"] = request.timeout
        return SimpleNamespace(
            get_instances=lambda: [SimpleNamespace(get_id=lambda: "registered-instance")],
        )

    engine = SimpleNamespace(async_get_instances=get_instances)

    def init_context(config, **_kwargs):
        connector = config.get_global().get_server_connector()
        recorded["connect_timeout"] = connector.connect_timeout
        recorded["message_timeout"] = connector.message_time
        recorded["api_timeout"] = config.get_global().get_api().timeout
        return SimpleNamespace(
            get_engine=lambda: engine,
            destroy=lambda: recorded.setdefault("destroyed", True),
        )

    env = {
        "POLARIS_E2E": "1",
        "POLARIS_E2E_CONNECT_TIMEOUT_MS": "6000",
        "POLARIS_E2E_MESSAGE_TIMEOUT_MS": "16000",
        "POLARIS_E2E_API_TIMEOUT_MS": "17000",
        "POLARIS_DEMO_RUN_DIR": str(tmp_path),
    }
    monkeypatch.delenv("POLARIS_E2E", raising=False)
    monkeypatch.setattr(real, "init_context_by_config", init_context)

    real.wait_for_provider(
        "registry:8091", "ns", "agent", "registered-instance", env,
    )

    assert recorded == {
        "connect_timeout": 6000,
        "message_timeout": 16000,
        "api_timeout": 17000,
        "request_timeout": 17000,
        "destroyed": True,
    }


def test_real_verifier_starts_demo_without_forcing_a_fork(tmp_path, monkeypatch):
    from integration import _real_verify as real

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    script = demo_dir / "main.py"
    script.write_text(
        "import json, os, time\n"
        f"print(json.dumps({{'ready': os.getcwd() == {str(demo_dir)!r}}}), flush=True)\n"
        "time.sleep(2)\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    env = {
        **os.environ,
        "POLARIS_DEMO_RUN_DIR": str(run_dir),
        "POLARIS_DEMO_DIRECTORY": str(demo_dir),
    }
    observed = {}
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        observed.update(kwargs)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(real.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(real, "record_external_process", lambda *_args, **_kwargs: None)
    process, payload = real.start_demo(script, [], env, "ready", timeout=5)
    try:
        assert payload == {"ready": True}
        assert observed["close_fds"] is False
        assert "cwd" not in observed
        assert "start_new_session" not in observed
    finally:
        process.terminate()
        process.communicate(timeout=5)


def test_real_verifier_one_shot_demo_also_avoids_fork(tmp_path, monkeypatch):
    from integration import _real_verify as real

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    script = demo_dir / "main.py"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    env = {
        **os.environ,
        "POLARIS_DEMO_RUN_DIR": str(run_dir),
        "POLARIS_DEMO_DIRECTORY": str(demo_dir),
    }
    observed = {}

    def recording_run(command, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, '{"ok": true}\n', "")

    monkeypatch.setattr(real.subprocess, "run", recording_run)
    assert real.run_demo(script, [], env, timeout=5) == '{"ok": true}\n'
    assert observed["close_fds"] is False
    assert "cwd" not in observed


def test_real_instance_host_uses_polaris_route_source_ip(monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        @staticmethod
        def getsockname():
            return "10.6.85.49", 54321

    monkeypatch.setattr(support.socket, "create_connection", lambda *args, **kwargs: Connection())
    assert get_local_host("127.0.0.1:8091") == "10.6.85.49"


@pytest.mark.parametrize("relative_path", [
    "quickstart/provider/main.py",
    "circuitbreaker/provider/main.py",
    "multicontext/main.py",
    "mcp/main.py",
    "monitoring/main.py",
    "lossless/provider/main.py",
])
def test_real_instance_registration_uses_local_route_host(relative_path):
    source = (REPO / "examples" / relative_path).read_text(encoding="utf-8")
    assert "get_local_host(" in source


def test_examples_do_not_depend_on_integration_or_e2e_runtime_config():
    for path in (REPO / "examples").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        assert "from integration" not in source, path
        assert "import integration" not in source, path
        assert "configure_e2e_event_reporting" not in source, path
        assert "POLARIS_E2E" not in source, path


def test_integration_uses_owned_fixtures_instead_of_importing_examples():
    for path in (REPO / "integration").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        assert "from examples" not in source, path
        assert "import examples" not in source, path


def test_lossless_fixture_allows_delay_longer_than_thirty_seconds(monkeypatch, tmp_path):
    from integration.fixtures import lossless_provider as lossless

    clock = {"seconds": 0.0}
    scheduled = {}
    destroyed = []

    async def schedule(request):
        scheduled["request"] = request

    async def deregister(_request):
        scheduled["deregistered"] = True

    provider = SimpleNamespace(
        context=SimpleNamespace(
            engine=SimpleNamespace(admin_server=SimpleNamespace(port=1235)),
        ),
        async_lossless_register=schedule,
        async_lossless_deregister=deregister,
        destroy=lambda: destroyed.append(True),
    )

    async def noop(*_args, **_kwargs):
        return None

    runner = SimpleNamespace(setup=noop, cleanup=noop)
    site = SimpleNamespace(
        start=noop,
        _server=SimpleNamespace(
            sockets=[SimpleNamespace(getsockname=lambda: ("127.0.0.1", 1234))],
        ),
    )
    config = Configuration()
    config.set_default()

    class Application:
        def __init__(self):
            self.router = SimpleNamespace(add_get=lambda *_args, **_kwargs: None)

        def __setitem__(self, key, value):
            raise AssertionError(f"started aiohttp application state must not be mutated: {key}")

    args = SimpleNamespace(
        config="unused.yaml",
        namespace="ns",
        service="agent",
        service_token="",
        version="v1",
        host="127.0.0.1",
        listen_host="127.0.0.1",
        port=1234,
        admin_host="127.0.0.1",
        admin_port=1235,
        ttl=5,
    )

    async def scenario():
        stop = asyncio.Event()

        async def advance(seconds):
            clock["seconds"] += seconds
            if clock["seconds"] >= 31:
                scheduled["request"].instance_id = "delayed-instance"
                stop.set()

        fake_loop = SimpleNamespace(
            time=lambda: clock["seconds"],
            add_signal_handler=lambda *_args: None,
        )
        monkeypatch.setattr(lossless.asyncio, "get_running_loop", lambda: fake_loop)
        monkeypatch.setattr(lossless.asyncio, "sleep", advance)
        monkeypatch.setattr(lossless.Configuration, "from_file", lambda _path: config)
        monkeypatch.setattr(lossless, "create_provider_by_config", lambda *_args, **_kwargs: provider)
        monkeypatch.setattr(lossless, "configure_e2e_event_reporting", lambda *_: None)
        monkeypatch.setattr(lossless, "demo_backup_directory", lambda *_args, **_kwargs: tmp_path)
        monkeypatch.setattr(lossless, "demo_log_options", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(lossless.web, "Application", Application)
        monkeypatch.setattr(lossless.web, "AppRunner", lambda *_args, **_kwargs: runner)
        monkeypatch.setattr(lossless.web, "TCPSite", lambda *_args, **_kwargs: site)
        await lossless.run(args, stop=stop)

    asyncio.run(scenario())

    assert scheduled["request"].instance_id == "delayed-instance"
    assert clock["seconds"] >= 31
    assert scheduled["deregistered"]
    assert destroyed


def test_lossless_consumer_disables_stat_reporter_without_admin_listener():
    config = Configuration.from_file(
        str(REPO / "integration/fixtures/config/lossless/consumer.yaml"),
        apply_env=False,
    )
    config.set_default()
    assert config.get_global().get_admin().port == -1
    assert not config.get_global().get_stat_reporter().is_enable()


def test_a2a_rejects_legacy_fields_from_1_0_card():
    from integration.fixtures import a2a as a2a_demo

    card = {
        "name": "agent",
        "version": "1.0.0",
        "protocolVersion": "0.3.0",
        "supportedInterfaces": [
            {"url": "http://127.0.0.1:8080/a2a", "protocolBinding": "JSONRPC"},
        ],
        "url": "http://127.0.0.2:8080/a2a",
        "preferredTransport": "JSONRPC",
    }
    with pytest.raises(ValueError, match="0.3 schema fields"):
        a2a_demo.parse_agent_card(card, "1.0")


def test_a2a_rejects_1_0_fields_from_0_3_card():
    from integration.fixtures import a2a as a2a_demo

    card = {
        "protocolVersion": "0.3.0",
        "name": "agent",
        "version": "1.0.0",
        "url": "http://127.0.0.1:8080/a2a",
        "preferredTransport": "JSONRPC",
        "supportedInterfaces": [
            {"url": "http://127.0.0.2:8080/a2a", "protocolBinding": "JSONRPC"},
        ],
    }
    with pytest.raises(ValueError, match="1.0 field supportedInterfaces"):
        a2a_demo.parse_agent_card(card, "0.3")


def test_a2a_legacy_card_uses_optional_interface_defaults():
    from integration.fixtures import a2a as a2a_demo

    card = {
        "protocolVersion": "0.3.0",
        "name": "agent",
        "version": "1.0.0",
        "url": "http://127.0.0.1:8080/a2a",
        "additionalInterfaces": None,
    }
    registration = a2a_demo.parse_agent_card(card, "0.3")
    assert registration["interfaces"] == [{
        "url": "http://127.0.0.1:8080/a2a",
        "transport": "JSONRPC",
    }]


@pytest.mark.parametrize(("a2a_version", "card"), [
    ("1.0", {
        "name": "agent",
        "version": "1.0.0",
        "supportedInterfaces": [{
            "url": " http://127.0.0.1:8080/a2a",
            "protocolBinding": "JSONRPC",
        }],
    }),
    ("1.0", {
        "name": "agent",
        "version": "1.0.0",
        "supportedInterfaces": [{
            "url": "http://127.0.0.1:8080/a2a",
            "protocolBinding": " JSONRPC ",
        }],
    }),
    ("0.3", {
        "protocolVersion": "0.3.0",
        "name": "agent",
        "version": "1.0.0",
        "url": "http://127.0.0.1:8080/a2a ",
    }),
    ("0.3", {
        "protocolVersion": "0.3.0",
        "name": "agent",
        "version": "1.0.0",
        "url": "http://127.0.0.1:8080/a2a",
        "preferredTransport": "JSONRPC ",
    }),
    ("0.3", {
        "protocolVersion": "0.3.0",
        "name": "agent",
        "version": "1.0.0",
        "url": "http://127.0.0.1:8080/a2a",
        "additionalInterfaces": [{
            "url": " http://127.0.0.1:9090/grpc",
            "transport": "GRPC",
        }],
    }),
])
def test_a2a_rejects_surrounding_whitespace_in_interface_fields(a2a_version, card):
    from integration.fixtures import a2a as a2a_demo

    with pytest.raises(ValueError, match="leading or trailing whitespace"):
        a2a_demo.parse_agent_card(card, a2a_version)


def test_a2a_rejects_embedded_url_controls_before_parsing():
    from integration.fixtures import a2a as a2a_demo

    for control in ("\n", "\r", "\t", "\x00", "\x7f"):
        card = {
            "name": "agent",
            "version": "1.0.0",
            "supportedInterfaces": [{
                "url": f"http://127.0.0.{control}1:8080/a2a",
                "protocolBinding": "JSONRPC",
            }],
        }
        with pytest.raises(ValueError, match="control characters"):
            a2a_demo.parse_agent_card(card, "1.0")


def test_a2a_registration_result_is_selected_by_instance_id():
    from integration.fixtures import a2a as a2a_demo

    class Node:
        def __init__(self, instance_id):
            self.instance_id = instance_id

        def get_id(self):
            return self.instance_id

    other, registered = Node("other-instance"), Node("registered-instance")
    instances = [other, registered]
    assert a2a_demo.find_registered_instance(instances, registered.get_id()) is registered
    assert a2a_demo.find_registered_instance(instances, "missing-instance") is None


def test_a2a_waits_for_current_card_after_stale_discovery_snapshot(tmp_path, monkeypatch):
    from integration.fixtures import a2a as a2a_demo

    old_card = {
        "name": "agent",
        "version": "1.0.0",
        "supportedInterfaces": [{
            "url": "http://127.0.0.1:8080/a2a",
            "protocolBinding": "JSONRPC",
        }],
    }
    current_card = {**old_card, "version": "2.0.0"}
    old_text, current_text = json.dumps(old_card), json.dumps(current_card)
    card_path = tmp_path / "card.json"
    card_path.write_text(current_text, encoding="utf-8")

    class Node:
        def __init__(self, card_text, card_version):
            self.card_text = card_text
            self.card_version = card_version

        def get_metadata(self):
            return {
                "ai-agent-name": "agent",
                "ai-agent-card": self.card_text,
                "ai-a2a-version": "1.0",
            }

        def get_host(self):
            return "127.0.0.1"

        def get_port(self):
            return 1

        def get_version(self):
            return self.card_version

        def get_protocol(self):
            return ""

        def get_id(self):
            return "registered-instance"

    old_node = Node(old_text, "1.0.0")
    current_node = Node(current_text, "2.0.0")
    snapshots = [
        SimpleNamespace(instances=[old_node]),
        SimpleNamespace(instances=[current_node]),
    ]
    destroy_calls = []

    async def register(_request):
        return SimpleNamespace(instance_id="registered-instance")

    async def deregister(_request):
        return None

    async def discover(_request):
        return snapshots.pop(0)

    provider = SimpleNamespace(
        async_register_instance=register,
        async_deregister_instance=deregister,
    )
    consumer = SimpleNamespace(async_get_all_instances=discover)
    context = SimpleNamespace(destroy=lambda: destroy_calls.append(True))
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

    monkeypatch.setattr(a2a_demo, "configure_e2e_event_reporting", lambda *_: None)
    monkeypatch.setattr(a2a_demo, "demo_backup_directory", lambda *_: tmp_path)
    monkeypatch.setattr(a2a_demo, "demo_log_options", lambda *_: None)
    monkeypatch.setattr(a2a_demo, "init_context_by_config", lambda *_args, **_kwargs: context)
    monkeypatch.setattr(a2a_demo, "ProviderAPI", lambda _context: provider)
    monkeypatch.setattr(a2a_demo, "ConsumerAPI", lambda _context: consumer)

    result = a2a_demo.run(args)

    assert result["version"] == "2.0.0"
    assert not snapshots
    assert destroy_calls


def test_a2a_stop_signal_during_discovery_deregisters_and_destroys(tmp_path, monkeypatch):
    from integration.fixtures import a2a as a2a_demo

    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps({
        "name": "agent",
        "version": "1.0.0",
        "supportedInterfaces": [{
            "url": "http://127.0.0.1:8080/a2a",
            "protocolBinding": "JSONRPC",
        }],
    }), encoding="utf-8")
    handlers = {}
    restored = []
    calls = []

    def fake_signal(signum, handler):
        if callable(handler):
            handlers[signum] = handler
            return object()
        restored.append((signum, handler))
        return None

    class Context:
        def destroy(self):
            calls.append("destroy")

    async def register(_request):
        calls.append("register")
        return SimpleNamespace(instance_id="registered-instance")

    async def deregister(_request):
        calls.append("deregister")

    async def discover(_request):
        calls.append("discover")
        loop = asyncio.get_running_loop()
        loop.call_soon(handlers[signal.SIGTERM], signal.SIGTERM, None)
        await asyncio.sleep(3600)

    provider = SimpleNamespace(
        async_register_instance=register,
        async_deregister_instance=deregister,
    )
    consumer = SimpleNamespace(async_get_all_instances=discover)
    context = Context()
    args = SimpleNamespace(
        card=str(card_path),
        a2a_version="1.0",
        namespace="ns",
        server="offline:8091",
        token="",
        registration_port=1,
        duration=0,
        keep_running=True,
    )

    monkeypatch.setattr(a2a_demo.signal, "signal", fake_signal)
    monkeypatch.setattr(a2a_demo, "configure_e2e_event_reporting", lambda *_: None)
    monkeypatch.setattr(a2a_demo, "demo_backup_directory", lambda *_: tmp_path)
    monkeypatch.setattr(a2a_demo, "demo_log_options", lambda *_: None)
    monkeypatch.setattr(a2a_demo, "init_context_by_config", lambda *_args, **_kwargs: context)
    monkeypatch.setattr(a2a_demo, "ProviderAPI", lambda _context: provider)
    monkeypatch.setattr(a2a_demo, "ConsumerAPI", lambda _context: consumer)

    async def scenario():
        stop = asyncio.Event()
        with a2a_demo.capture_stop_signals(asyncio.get_running_loop(), stop):
            return await asyncio.wait_for(a2a_demo._run(args, stop), timeout=1)

    result = asyncio.run(scenario())
    assert result["stopped"]
    assert calls == ["register", "discover", "deregister", "destroy"]
    assert {signum for signum, _ in restored} == {signal.SIGINT, signal.SIGTERM}


def test_monitoring_stop_signals_do_not_require_add_signal_handler(monkeypatch):
    from integration.fixtures import monitoring

    installed = {}
    restored = []
    callbacks = []

    def install(signum, handler):
        previous = installed.get(signum, object())
        installed[signum] = handler
        return previous

    def restore(signum, handler):
        restored.append((signum, handler))

    class Loop:
        @staticmethod
        def call_soon_threadsafe(callback):
            callbacks.append(callback)

    class Stop:
        stopped = False

        def set(self):
            self.stopped = True

    stop = Stop()
    monkeypatch.setattr(monitoring.signal, "signal", install)
    with monitoring.capture_stop_signals(Loop(), stop):
        installed[signal.SIGINT](signal.SIGINT, None)
        callbacks.pop()()
        assert stop.stopped

    monkeypatch.setattr(monitoring.signal, "signal", restore)
    with monitoring.capture_stop_signals(Loop(), Stop()):
        pass
    assert {signum for signum, _ in restored} == {signal.SIGINT, signal.SIGTERM}


@pytest.mark.parametrize("phase", ["registration", "discovery", "http"])
def test_monitoring_startup_stop_deregisters_and_destroys(phase, tmp_path, monkeypatch):
    from integration.fixtures import monitoring

    calls = []
    reported_codes = []

    async def noop(*_args, **_kwargs):
        return None

    async def register(_request):
        calls.append("register")
        if phase == "registration":
            stop.set()
        return SimpleNamespace(instance_id="registered-instance")

    async def deregister(_request):
        calls.append("deregister")

    async def discover(_request):
        calls.append("discover")
        if phase == "discovery":
            stop.set()
            await asyncio.sleep(3600)
        if phase == "http":
            return SimpleNamespace(
                get_host=lambda: "127.0.0.1",
                get_port=lambda: 1234,
            )
        return None

    async def report(_request):
        calls.append("report")
        reported_codes.append(_request.ret_code)

    async def unexpected_report(_request):
        raise AssertionError("stop must prevent metric reporting")

    class Context:
        def destroy(self):
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
            if phase == "http":
                asyncio.get_running_loop().call_later(0.01, stop.set)
                await asyncio.sleep(3600)
            return b"echo"

    class GetRequest:
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
        def get(_url):
            calls.append("http")
            return GetRequest()

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
        async_get_one_instance=discover,
        async_update_service_call_result=report if phase == "http" else unexpected_report,
    )
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
    )

    monkeypatch.setattr(monitoring, "configure_e2e_event_reporting", lambda *_: None)
    monkeypatch.setattr(monitoring, "demo_backup_directory", lambda *_: tmp_path)
    monkeypatch.setattr(monitoring, "demo_log_options", lambda *_: None)
    monkeypatch.setattr(
        monitoring, "init_context_by_config", lambda *_args, **_kwargs: Context(),
    )
    monkeypatch.setattr(monitoring, "ProviderAPI", lambda _context: provider)
    monkeypatch.setattr(monitoring, "ConsumerAPI", lambda _context: consumer)
    monkeypatch.setattr(monitoring.web, "Application", Application)
    monkeypatch.setattr(monitoring.web, "AppRunner", lambda *_args, **_kwargs: Runner())
    monkeypatch.setattr(monitoring.web, "TCPSite", lambda *_args, **_kwargs: site)
    monkeypatch.setattr(monitoring, "ClientSession", Client)

    async def scenario():
        return await asyncio.wait_for(monitoring._run(args, stop, True), timeout=1)

    stop = asyncio.Event()
    result = asyncio.run(scenario())

    assert result["stopped"]
    expected = ["register"]
    if phase != "registration":
        expected.append("discover")
    if phase == "http":
        expected.extend(["discover", "http", "report"])
        assert reported_codes == [-1]
    expected.extend(["deregister", "destroy", "cleanup"])
    assert calls == expected


def test_monitoring_stop_interrupts_duration_wait():
    from integration.fixtures import monitoring

    async def scenario():
        stop = asyncio.Event()
        asyncio.get_running_loop().call_later(0.01, stop.set)
        return await asyncio.wait_for(monitoring._wait_for_stop(stop, 31), timeout=1)

    assert asyncio.run(scenario())


def test_multicontext_verifier_checks_post_exit_cleanup(tmp_path, monkeypatch):
    from integration.scenarios.multicontext import verify

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
                         "consumer.get_service_contract(")),
    ("cache/expiry/main.py", ("consumer.get_instances(",)),
    ("cache/restart/verify.py", ("consumer.get_instances(",)),
    ("sdkconfig/code/main.py", ("consumer.get_instances(",)),
    ("sdkconfig/file/main.py", ("consumer.get_instances(",)),
    ("multicontext/main.py", ("sync_discover(", "consumer.get_instances(")),
    ("events/main.py", ("consumer.get_instances(", "get_event_center().register_listener(")),
    ("lossless/provider/main.py", ("provider.async_lossless_register(", "provider.async_lossless_deregister(")),
    ("lossless/consumer/main.py", ("consumer.async_get_one_instance(",)),
])
def test_demo_default_or_verifier_paths_cover_synchronous_apis(relative_path, calls):
    path = REPO / "examples" / relative_path
    if not path.exists():
        path = REPO / "integration" / "scenarios" / relative_path
    source = path.read_text(encoding="utf-8")
    for call in calls:
        assert call in source, f"{relative_path} does not call {call}"


def test_restart_backup_glob_matches_svc_cache_files(tmp_path):
    service = "polaris-python-e2e-cache-restart-53e071ea"
    (tmp_path / f"svc#default#{service}#instance.json").write_text("{}", encoding="utf-8")
    assert any(tmp_path.glob(cache_backup_glob("default", service)))


@pytest.mark.parametrize("name", sorted(set(manager.VERIFIERS) | set(manager.GROUPS)))
def test_scenario_documentation_describes_verification(name):
    directory = REPO / "examples" / name
    documentation = (
        REPO / "integration" / "test.md"
        if not name
        else REPO / "integration" / "scenarios" / name / "test.md"
    )
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


def test_example_registry_matches_makefile_and_scenario_files():
    makefile = (REPO / "examples" / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^SUBDIRS\s*:=\s*(.+)$", makefile, re.MULTILINE)
    assert match is not None
    makefile_entries = set(match.group(1).split())
    registry_entries = {name.split("/", 1)[0] for name in manager.VERIFIERS}
    registry_entries.update(name for name in manager.GROUPS if name)
    assert makefile_entries == registry_entries
    for name, (script, _) in manager.VERIFIERS.items():
        assert (REPO / "integration" / "scenarios" / script).is_file(), name


def test_macos_ds_store_is_ignored():
    result = subprocess.run(["git", "check-ignore", "-q", ".DS_Store"], cwd=REPO)
    assert result.returncode == 0


@pytest.mark.parametrize("script", ["verify.sh", "verify_e2e.sh", "logs.sh", "cleanup.sh"])
def test_integration_scripts_print_usage(script):
    path = REPO / "integration" / script
    assert os.access(path, os.X_OK)
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is unavailable")
    result = subprocess.run([bash, path.as_posix(), "--help"], cwd=REPO,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


@pytest.fixture
def example_tree(monkeypatch, tmp_path):
    root = tmp_path / "examples"
    integration = tmp_path / "integration"
    monkeypatch.setattr(manager, "EXAMPLES", root)
    monkeypatch.setattr(manager, "INTEGRATION", integration)
    monkeypatch.setattr(manager, "SCENARIOS", integration / "scenarios")
    monkeypatch.setattr(manager, "LOG_ROOT", integration / ".logs")
    monkeypatch.setattr(manager, "RUNTIME_ROOT", integration / ".runtime")
    monkeypatch.setattr(manager, "REPO", tmp_path)
    for name in ("sdkconfig", "sdkconfig/code", "sdkconfig/file"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def test_cleanup_preview_and_removal_are_scoped_to_selected_demo(example_tree, capsys):
    selected = example_tree / "sdkconfig/code"
    other = example_tree / "sdkconfig/file"
    for directory in (selected, other):
        logs = manager.LOG_ROOT / directory.relative_to(example_tree)
        logs.mkdir(parents=True)
        (logs / "console.log").write_text("retained")
        (directory / "polaris.yaml").write_text("keep YAML")
    (selected / ".logs").mkdir()
    (selected / ".logs/console.log").write_text("manual demo")
    (selected / ".runtime").mkdir()
    (selected / ".runtime/manual-record").write_text("manual demo")
    manager.cleanup(selected, SimpleNamespace(force=True, dry_run=True))
    assert "Dry run" in capsys.readouterr().out
    assert (manager.LOG_ROOT / "sdkconfig/code/console.log").exists()
    manager.cleanup(selected, SimpleNamespace(force=True, dry_run=False))
    assert not (manager.LOG_ROOT / "sdkconfig/code").exists()
    assert (selected / ".logs/console.log").read_text() == "manual demo"
    assert (selected / ".runtime/manual-record").read_text() == "manual demo"
    assert (selected / "polaris.yaml").read_text() == "keep YAML"
    assert (manager.LOG_ROOT / "sdkconfig/file/console.log").read_text() == "retained"


def test_cleanup_keep_logs_stops_processes_but_preserves_logs(example_tree):
    selected = example_tree / "sdkconfig/code"
    owner = manager.RUNTIME_ROOT / "sdkconfig/code"
    logs = manager.LOG_ROOT / "sdkconfig/code"
    logs.mkdir(parents=True)
    (logs / "console.log").write_text("keep me", encoding="utf-8")
    code = ("import time; from integration._runtime import track_process; "
            f"track_process({str(owner)!r}, {str(selected / 'main.py')!r}); "
            "print('ready', flush=True); time.sleep(30)")
    process = subprocess.Popen([sys.executable, "-c", code], cwd=REPO,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert process.stdout.readline() == "ready\n"
    try:
        manager.cleanup(selected, SimpleNamespace(force=True, dry_run=False, keep_logs=True))
        process.wait(timeout=5)
        assert not psutil.pid_exists(process.pid)
        assert (logs / "console.log").read_text(encoding="utf-8") == "keep me"
        assert not owner.exists()
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
    (manager.LOG_ROOT / "sdkconfig").mkdir(parents=True)
    (manager.LOG_ROOT / "sdkconfig/code").symlink_to(external, target_is_directory=True)
    (manager.RUNTIME_ROOT / "sdkconfig").mkdir(parents=True)
    (manager.RUNTIME_ROOT / "sdkconfig/code").symlink_to(external, target_is_directory=True)
    assert manager.log_files(selected) == []
    manager.cleanup(selected, SimpleNamespace(force=True, dry_run=False))
    assert (external / "keep.log").read_text() == "external data"


def test_category_log_filter_does_not_match_the_demo_directory(example_tree, monkeypatch, capsys):
    monkeypatch.setitem(manager.VERIFIERS, "circuitbreaker", ("unused.py", []))
    selected = example_tree / "circuitbreaker"
    run = manager.LOG_ROOT / "circuitbreaker/verify-1"
    for category in ("base", "circuitbreaker"):
        path = run / "polaris" / "log" / category / f"polaris-{category}.log"
        path.parent.mkdir(parents=True)
        path.write_text(category)
    manager.show_logs(selected, SimpleNamespace(category="circuitbreaker", latest=True, follow=False, tail=1))
    output = capsys.readouterr().out
    assert "polaris-circuitbreaker.log" in output
    assert "polaris-base.log" not in output


def test_latest_integration_logs_are_selected_per_leaf_scenario(example_tree, capsys):
    paths = []
    for name, stamp in (("code", 100), ("file", 200)):
        for run, offset in (("verify-old", 0), ("verify-new", 1)):
            path = manager.LOG_ROOT / "sdkconfig" / name / run / "console.log"
            path.parent.mkdir(parents=True)
            path.write_text(f"{name}-{run}", encoding="utf-8")
            os.utime(path.parent, (stamp + offset, stamp + offset))
            if offset:
                paths.append(path)
    manager.show_logs(
        example_tree / "sdkconfig",
        SimpleNamespace(category=None, latest=True, follow=False, tail=0),
    )
    output = capsys.readouterr().out
    assert all(str(path) in output for path in paths)
    assert "verify-old" not in output


def test_verification_retains_output_on_failure_and_restores_environment(tmp_path, monkeypatch):
    entry = tmp_path / "demo/verify.py"
    entry.parent.mkdir()
    entry.touch()
    monkeypatch.delenv("POLARIS_DEMO_RUN_DIR", raising=False)
    monkeypatch.delenv("POLARIS_DEMO_DIRECTORY", raising=False)
    monkeypatch.setattr(runtime, "_tracked", set())
    monkeypatch.setattr(runtime, "LOG_ROOT", tmp_path / "integration/.logs")
    monkeypatch.setattr(runtime, "RUNTIME_ROOT", tmp_path / "integration/.runtime")
    with pytest.raises(RuntimeError, match="failed verification"):
        with runtime.verification_directory(entry) as directory:
            directory.joinpath("cache").mkdir()
            print("inspect this failure")
            raise RuntimeError("failed verification")
    logs = list((tmp_path / "integration/.logs").rglob("verification.log"))
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
    options = support.demo_log_options(entry, component="consumer")
    backup = support.demo_backup_directory(entry, component="consumer")
    assert Path(options.log_dir) == run / "polaris" / "log" / "consumer"
    assert backup == run / "polaris" / "backup" / "consumer"
    assert backup.parent.parent == Path(options.log_dir).parent.parent == run / "polaris"
    monkeypatch.delenv("POLARIS_DEMO_RUN_DIR")
    assert support.demo_backup_directory(entry, component="consumer") == (
        entry.parent / ".logs" / "manual" / "polaris" / "backup" / "consumer"
    )


def test_cleanup_stops_owned_process_and_keeps_other_demo_alive(example_tree):
    owned, other = example_tree / "sdkconfig/code", example_tree / "sdkconfig/file"

    def start(directory):
        owner = manager.RUNTIME_ROOT / directory.relative_to(example_tree)
        code = ("import time; from integration._runtime import track_process; "
                f"track_process({str(owner)!r}, {str(directory / 'main.py')!r}); "
                "print('ready', flush=True); time.sleep(30)")
        process = subprocess.Popen([sys.executable, "-c", code], cwd=REPO,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert process.stdout.readline() == "ready\n"
        return process

    first, second = start(owned), start(other)
    try:
        # Simulate an old record with a PID reused by the other demo.
        record = (
            manager.RUNTIME_ROOT
            / "sdkconfig/code"
            / "processes"
            / f"{second.pid}.json"
        )
        record.write_text(json.dumps({"pid": second.pid, "created": 0,
                                     "command": psutil.Process(second.pid).cmdline(),
                                     "entry": str(owned / "main.py")}))
        manager.cleanup(owned, SimpleNamespace(force=True, dry_run=False))
        first.wait(timeout=5)
        assert not psutil.pid_exists(first.pid)
        assert second.poll() is None
        assert (
            manager.RUNTIME_ROOT / "sdkconfig/file"
        ).exists()
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
    result = next((manager.LOG_ROOT / "sdkconfig/code").glob("verify-*/result.json"))
    assert json.loads(result.read_text())["timed_out"] is True
    assert result.with_name("console.log").exists()


def test_verification_timeout_is_forwarded_to_scenario_process(example_tree):
    selected = example_tree / "sdkconfig/code"
    entry = selected / "verify.py"
    entry.write_text(
        "import os; print(os.environ['POLARIS_E2E_SCENARIO_TIMEOUT_SECONDS'])",
        encoding="utf-8",
    )

    assert manager.run_process(selected, entry, [], "verify-e2e", 321) == 0
    console = next((manager.LOG_ROOT / "sdkconfig/code").glob("verify-e2e-*/console.log")).read_text(encoding="utf-8")
    assert console.strip() == "321"


@pytest.mark.skipif(os.name == "nt", reason="Windows does not deliver SIGTERM to Python handlers")
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
    result = json.loads(next((manager.LOG_ROOT / "sdkconfig/code").glob("verify-*/result.json")).read_text())
    assert result["exit_code"] == 0
    assert result["interrupted"] == signal.SIGTERM


def test_interrupted_group_does_not_start_remaining_demos(example_tree, monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["_manage.py", "--directory", str(example_tree / "sdkconfig"), "verify"])

    def interrupt(directory, *args):
        calls.append(directory)
        return 128 + signal.SIGINT

    monkeypatch.setattr(manager, "run_process", interrupt)
    assert manager.main() == 128 + signal.SIGINT
    assert calls == [example_tree / "sdkconfig/code"]
