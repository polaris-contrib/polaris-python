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

"""Run demo scenarios against a real Polaris server and verify observable effects."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import psutil
import yaml
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote_plus
from urllib.request import ProxyHandler, Request, build_opener

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
E2E_SKILL_FIXTURE_NAME = "polaris-python-e2e-skill-fixture"
DEFAULT_E2E_SCENARIO_TIMEOUT_SECONDS = 600
DEMO_STARTUP_TIMEOUT_MARGIN_SECONDS = 15

sys.path[:0] = [str(REPO / "src"), str(REPO)]
from integration._support import (
    DEFAULT_E2E_API_TIMEOUT_MS,
    DEFAULT_E2E_CONNECT_TIMEOUT_MS,
    DEFAULT_E2E_MESSAGE_TIMEOUT_MS,
    DEFAULT_E2E_SKILL_DOWNLOAD_TIMEOUT_MS,
    DEFAULT_E2E_SKILL_TIMEOUT_MS,
    configure_e2e_event_reporting,
    get_local_host,
)
from integration._runtime import (
    E2E_SERVICE_ROLES,
    record_external_process,
    resolve_e2e_namespace,
    verification_directory,
)
from polaris import Configuration, SDKEventName, SkillAPI, init_context_by_config
from polaris.api.log import LogOptions
from polaris.pkg.model.error import SDKError
from polaris.pkg.model.service import GetInstancesRequest
from polaris.pkg.model.skill import SkillListRequest


def required_environment():
    address = os.getenv("POLARIS_SERVER_ADDRESS") or os.getenv("POLARIS_SERVER_ADDRESSES")
    if not address:
        raise RuntimeError("POLARIS_SERVER_ADDRESS is required for real-service verification")
    address = address.split(",", 1)[0].strip()
    service_token = (
        os.getenv("POLARIS_E2E_SERVICE_TOKEN")
        or os.getenv("POLARIS_SERVICE_TOKEN")
        or ""
    )
    return address, service_token


def resolve_skill_namespace(instance_namespace, *, configured_name="", configured_namespace=""):
    """Keep automatic Skill discovery and fixtures in the isolated E2E namespace."""
    if configured_namespace:
        return configured_namespace
    return "default" if configured_name else instance_namespace


def scenario_environment(address):
    env = os.environ.copy()
    registry_host = address.rsplit(":", 1)[0].strip("[]")
    env.update(
        POLARIS_E2E="1",
        POLARIS_SERVER_ADDRESS=address,
        POLARIS_SERVER=address,
        POLARIS_SERVER_ADDRESSES=address,
        POLARIS_API_TIMEOUT=str(DEFAULT_E2E_API_TIMEOUT_MS),
        POLARIS_EVENT_REPORTER_ENABLE="1",
        POLARIS_EVENT_REPORTER_ADDRESS=f"{registry_host}:9091",
        POLARIS_EVENT_REPORTER_PUSH_INTERVAL="250",
        POLARIS_EVENT_REPORTER_MAX_RETRIES="3",
        POLARIS_EVENT_REPORTER_RETRY_INTERVAL="100",
        PYTHONUNBUFFERED="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    env.setdefault("POLARIS_E2E_CONNECT_TIMEOUT_MS", str(DEFAULT_E2E_CONNECT_TIMEOUT_MS))
    env.setdefault("POLARIS_E2E_MESSAGE_TIMEOUT_MS", str(DEFAULT_E2E_MESSAGE_TIMEOUT_MS))
    env.setdefault("POLARIS_E2E_API_TIMEOUT_MS", str(DEFAULT_E2E_API_TIMEOUT_MS))
    env.setdefault("POLARIS_E2E_SKILL_TIMEOUT_MS", str(DEFAULT_E2E_SKILL_TIMEOUT_MS))
    env.setdefault(
        "POLARIS_E2E_SKILL_DOWNLOAD_TIMEOUT_MS",
        str(DEFAULT_E2E_SKILL_DOWNLOAD_TIMEOUT_MS),
    )
    env.setdefault(
        "POLARIS_E2E_SCENARIO_TIMEOUT_SECONDS",
        str(DEFAULT_E2E_SCENARIO_TIMEOUT_SECONDS),
    )
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [
        str(REPO / "src"), str(REPO), env.get("PYTHONPATH", ""),
    ]))
    return env


def e2e_namespace():
    """Return the namespace for services created by real-service verification."""
    return resolve_e2e_namespace()


def service_name(scenario, role="provider"):
    """Build a scenario service name with an explicit caller/callee/provider role."""
    if role not in E2E_SERVICE_ROLES:
        raise ValueError(
            f"unsupported E2E service role {role!r}; "
            f"choose from {', '.join(E2E_SERVICE_ROLES)}"
        )
    label = scenario.strip("/").replace("/", "-") or "scenario"
    now = datetime.now()
    stamp = now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"
    return f"{label}-{role}-{stamp}"


def scenario_timeout(env):
    """Return the outer verifier budget used for bounded startup operations."""
    raw = env.get(
        "POLARIS_E2E_SCENARIO_TIMEOUT_SECONDS",
        str(DEFAULT_E2E_SCENARIO_TIMEOUT_SECONDS),
    )
    try:
        timeout = float(raw)
    except ValueError as error:
        raise ValueError("POLARIS_E2E_SCENARIO_TIMEOUT_SECONDS must be a number") from error
    if not 0 < timeout <= 3600:
        raise ValueError("POLARIS_E2E_SCENARIO_TIMEOUT_SECONDS must be between 0 and 3600")
    return timeout


def scenario_api_timeout_ms(env):
    """Return the API timeout passed to demos as their CLI override."""
    raw = env.get("POLARIS_E2E_API_TIMEOUT_MS", str(DEFAULT_E2E_API_TIMEOUT_MS))
    try:
        timeout = int(raw)
    except (TypeError, ValueError) as error:
        raise ValueError("POLARIS_E2E_API_TIMEOUT_MS must be an integer") from error
    if timeout <= 0:
        raise ValueError("POLARIS_E2E_API_TIMEOUT_MS must be positive")
    return timeout


def scenario_operation_timeout(env, minimum=90):
    """Cover one configured API call without exceeding the outer scenario budget."""
    api_budget = scenario_api_timeout_ms(env) / 1000 + DEMO_STARTUP_TIMEOUT_MARGIN_SECONDS
    return min(scenario_timeout(env), max(float(minimum), api_budget))


def assert_instance_host(actual, address):
    """Require the advertised instance IP to match the Polaris route source IP."""
    expected = get_local_host(address)
    if actual != expected:
        raise AssertionError(f"instance host {actual!r} does not match local route IP {expected!r}")


def default_skill_address(address):
    """Derive the conventional Skill service address from the registry address."""
    host = address.rsplit(":", 1)[0].strip("[]")
    return f"[{host}]:8094" if ":" in host else f"{host}:8094"


def default_console_address(address):
    """Derive the conventional Polaris console address."""
    configured = os.getenv("POLARIS_CONSOLE_ADDRESS")
    if configured:
        return configured.rstrip("/")
    host = address.rsplit(":", 1)[0].strip("[]")
    return f"http://[{host}]:8090" if ":" in host else f"http://{host}:8090"


def console_json_request(address, method, path, payload=None):
    """Call a Polaris console JSON API and return its decoded response."""
    token = (
        os.getenv("POLARIS_CONSOLE_TOKEN")
        or os.getenv("POLARIS_TOKEN")
        or os.getenv("POLARIS_E2E_SERVICE_TOKEN")
        or os.getenv("POLARIS_SERVICE_TOKEN")
        or ""
    )
    headers = {"X-Polaris-Token": token}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(
        f"{default_console_address(address)}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
            body = response.read()
    except HTTPError as error:
        body = error.read()
        raise RuntimeError(
            f"Polaris console {method} {path} returned HTTP {error.code}: "
            f"{body.decode('utf-8', errors='replace')}"
        ) from error
    result = json.loads(body)
    if result.get("code") != 200000:
        raise RuntimeError(f"Polaris console {method} {path} failed: {result}")
    return result


def create_skill_fixture(address, namespace):
    """Create and immediately publish the reusable E2E Skill fixture."""
    name = E2E_SKILL_FIXTURE_NAME
    description = "Reusable Skill fixture created by the Python E2E verifier"
    content = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        "# Polaris Python E2E Skill\n\n"
        "This reusable fixture verifies published Skill discovery and download.\n"
    )
    console_json_request(address, "POST", "/skill/v1/skills", {
        "namespace": namespace,
        "name": name,
        "version": "1.0.0",
        "description": description,
        "content": content,
        "scope": "PRIVATE",
        "publish": True,
    })
    return name


def discover_skill_name(
        env, address, skill_address, namespace, *, expected_name="", timeout=0, fallback_to_first=True):
    """Select a published Skill, optionally waiting for one specific resource."""
    config = Configuration()
    configure_e2e_event_reporting(config, env)
    config.get_global().get_admin().port = 0
    config.get_global().get_server_connector().addresses = [address]
    config.get_global().get_server_connector().token = os.getenv("POLARIS_TOKEN", "")
    config.get_global().get_api().bind_ip = "127.0.0.1"
    connector = config.get_ai().get_skill().get_server_connector()
    connector.addresses = [skill_address]
    connector.token = os.getenv("POLARIS_SKILL_TOKEN", os.getenv("POLARIS_TOKEN", ""))
    connector.persist_enable = False
    run = Path(env["POLARIS_DEMO_RUN_DIR"])
    config.get_consumer().get_local_cache().persist_dir = str(run / "polaris" / "backup" / "skill-probe")
    context = init_context_by_config(
        config,
        log_options=LogOptions(log_dir=run / "polaris" / "log" / "skill-probe"),
    )
    deadline = time.monotonic() + timeout
    try:
        api = SkillAPI(context)
        while True:
            response = api.list_skills(SkillListRequest(namespace=namespace, limit=100))
            names = sorted({item.name for item in response.resources if item.name})
            if expected_name:
                if expected_name in names:
                    return expected_name
                if fallback_to_first and names:
                    return names[0]
            elif names:
                return names[0]
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.5)
    finally:
        context.destroy()


def cache_backup_glob(namespace, service):
    """Match the svc#namespace#service#resource.json backups for one service."""
    return "svc#%s#%s#*.json" % (
        quote_plus(namespace, safe=""),
        quote_plus(service, safe=""),
    )


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def demo_process_command(script, arguments):
    """Build a posix_spawn-compatible command that preserves demo cwd semantics."""
    launcher = (
        "import os, runpy, sys\n"
        "repo = sys.argv[3]\n"
        "sys.path[:0] = [os.path.join(repo, 'src'), repo]\n"
        "from integration._support import install_example_event_reporting\n"
        "install_example_event_reporting()\n"
        "os.chdir(sys.argv[1])\n"
        "script = sys.argv[2]\n"
        "sys.argv = [script, *sys.argv[4:]]\n"
        "runpy.run_path(script, run_name='__main__')\n"
    )
    return [
        sys.executable,
        "-c",
        launcher,
        str(script.parent),
        str(script),
        str(REPO),
        *arguments,
    ]


def demo_output_name(script):
    """Return a stable output label without collapsing sibling fixture scripts."""
    script = Path(script)
    return script.parent.name if script.name == "main.py" else script.stem


def start_demo(script, arguments, env, expected_key, timeout=60):
    timeout = scenario_operation_timeout(env, timeout)
    run_dir = Path(env["POLARIS_DEMO_RUN_DIR"])
    output_path = run_dir / f"{demo_output_name(script)}.stdout.log"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            demo_process_command(script, arguments),
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            # cwd and start_new_session force fork() on macOS. Keeping cwd unset
            # lets Python use posix_spawn. Python-created descriptors are
            # non-inheritable by default, so close_fds=False does not expose
            # arbitrary parent descriptors after exec.
            close_fds=False,
        )
    record_external_process(env["POLARIS_DEMO_DIRECTORY"], psutil.Process(process.pid), script)
    process.demo_output_path = output_path
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = output_path.read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(f"{script} exited with {process.returncode} before {expected_key}: {output}")
        try:
            lines = output_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if value.get(expected_key):
                return process, value
        time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {expected_key} from {script.name}")


def stop_demo(process, log_path, description):
    if process.poll() is None:
        process.terminate()
    try:
        output, _ = process.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate(timeout=5)
    if output is None:
        demo_output = getattr(process, "demo_output_path", None)
        output = (
            Path(demo_output).read_text(encoding="utf-8", errors="replace")
            if demo_output
            else ""
        )
    output = "".join(getattr(process, "demo_lines", [])) + output
    Path(log_path).write_text(output, encoding="utf-8")
    if process.returncode != 0:
        raise RuntimeError(f"{description} exited with {process.returncode}:\n{output}")
    return output


def run_demo(script, arguments, env, timeout=90):
    timeout = scenario_operation_timeout(env, timeout)
    completed = subprocess.run(
        demo_process_command(script, arguments),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        close_fds=False,
    )
    output_name = demo_output_name(script)
    output_path = Path(env["POLARIS_DEMO_RUN_DIR"]) / f"{output_name}.stdout.log"
    output_path.write_text(completed.stdout, encoding="utf-8")
    (output_path.parent / f"{output_name}.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(
            f"{script} exited with {completed.returncode}:\n{completed.stderr or completed.stdout}"
        )
    return completed.stdout


def last_json(output):
    for line in reversed(output.splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"no JSON result in output:\n{output}")


def start_quickstart_provider(address, service_token, namespace, service, env, run):
    script = EXAMPLES / "quickstart/provider/main.py"
    process, payload = start_demo(script, [
        "--namespace", namespace,
        "--service", service,
        "--service-token", service_token,
        "--port", "0",
    ], env, "registered")
    return process, {
        "instance_id": payload["instance_id"],
        "host": payload["host"],
        "port": payload["port"],
    }


def with_provider(scenario, namespace, env, address, service_token, effect):
    service = service_name(scenario)
    provider, provider_info = start_quickstart_provider(
        address, service_token, namespace, service, env, Path(env["POLARIS_DEMO_RUN_DIR"]),
    )
    assert_instance_host(provider_info["host"], address)
    wait_for_provider(address, namespace, service, provider_info["instance_id"], env)
    result = effect(service, provider_info)
    if provider.poll() is not None:
        raise RuntimeError("real-service provider exited during verification")
    return {"service": service, "provider": provider_info, **result}


def request_json(url):
    try:
        with build_opener(ProxyHandler({})).open(url, timeout=10) as response:
            body = response.read()
            return response.status, json.loads(body)
    except HTTPError as error:
        with error:
            return error.code, json.loads(error.read())


def post_json(url, payload):
    """POST one JSON payload without proxy or authentication wrappers."""
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        with error:
            return error.code, json.loads(error.read())


def request_text(url):
    try:
        with build_opener(ProxyHandler({})).open(url, timeout=10) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        with error:
            return error.code, error.read().decode("utf-8", errors="replace")


def wait_for_text(url, expected, timeout=30):
    deadline = time.monotonic() + timeout
    last_value = ""
    while time.monotonic() < deadline:
        status, last_value = request_text(url)
        if status == 200 and last_value == expected:
            return status, last_value
        time.sleep(0.2)
    raise RuntimeError(f"HTTP endpoint {url} did not return {expected!r}: {last_value!r}")


def wait_for_provider(address, namespace, service, expected_id, env, timeout=90):
    run = Path(env["POLARIS_DEMO_RUN_DIR"])
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        config = Configuration()
        config.set_default()
        config.get_global().get_admin().port = 0
        connector = config.get_global().get_server_connector()
        connector.addresses = [address]
        connector.token = env.get("POLARIS_TOKEN", "")
        config.get_global().get_api().bind_ip = "127.0.0.1"
        config.get_consumer().get_local_cache().persist_dir = str(run / "polaris" / "backup" / "probe")
        configure_e2e_event_reporting(config, env)
        api_timeout_ms = config.get_global().get_api().get_timeout()
        context = init_context_by_config(
            config,
            log_options=LogOptions(log_dir=run / "polaris" / "log" / "probe"),
        )
        try:
            async def discover():
                result = await context.get_engine().async_get_instances(
                    GetInstancesRequest(
                        namespace=namespace,
                        service=service,
                        timeout=api_timeout_ms,
                        use_discover_cache=False,
                    )
                )
                return [instance.get_id() for instance in result.get_instances()]

            ids = asyncio.run(asyncio.wait_for(
                discover(), timeout=api_timeout_ms / 1000 + 5,
            ))
            if expected_id in ids:
                return
            last_error = AssertionError(f"instance {expected_id} not visible; got {ids}")
        except (AssertionError, OSError, SDKError, TimeoutError, RuntimeError) as error:
            last_error = error
        finally:
            context.destroy()
        time.sleep(0.5)
    raise RuntimeError(f"service {namespace}/{service} did not become visible: {last_error}")


def wait_for_http(url, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            status, body = request_json(url)
            if predicate(status, body):
                return status, body
            last_error = AssertionError(f"unexpected response {status}: {body}")
        except OSError as error:
            last_error = error
        time.sleep(0.5)
    raise RuntimeError(f"HTTP endpoint {url} did not become ready: {last_error}")


def wait_for_pushed_events(run, event_names, timeout=30):
    """Wait until SDK logs confirm each circuit event received a 2xx response."""
    deadline = time.monotonic() + timeout
    missing = list(event_names)
    logs = []
    while time.monotonic() < deadline:
        logs = [
            path.read_text(encoding="utf-8", errors="replace")
            for path in run.glob("polaris/log/**/event/*.log")
        ]
        output = "\n".join(logs)
        missing = [
            name for name in event_names
            if f"reported event to Pushgateway: CIRCUIT_BREAKING|{name}|" not in output
        ]
        if not missing:
            return
        time.sleep(0.2)
    raise RuntimeError(f"Circuit events were not accepted by Pushgateway: {missing}")


def assert_event_reporters_enabled(run):
    """Require every non-probe Context that logged initialization to use Pushgateway."""
    log_root = Path(run) / "polaris" / "log"
    states = {}
    for path in log_root.rglob("base/*.log"):
        if path.name.startswith("."):
            continue
        component = path.relative_to(log_root).parts[0]
        if component == "probe" or component.endswith("-probe"):
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "polaris engine initialized" not in line or "eventReporters=" not in line:
                continue
            state = line.split("eventReporters=", 1)[1].split(" statReporter=", 1)[0]
            states[path] = state
    expected = "['PushGatewayEventReporter']"
    disabled = [path for path, state in states.items() if state != expected]
    if disabled:
        details = ", ".join(
            f"{path.relative_to(run).as_posix()}={states[path]}" for path in disabled
        )
        raise RuntimeError(f"non-probe Contexts did not enable event reporting: {details}")
    if not states:
        raise RuntimeError("no non-probe Context logged event reporter initialization")


def verify_quickstart(env, address, service_token, namespace):
    service = service_name("quickstart")
    provider, provider_info = start_quickstart_provider(
        address, service_token, namespace, service, env, Path(env["POLARIS_DEMO_RUN_DIR"]),
    )
    assert_instance_host(provider_info["host"], address)
    consumer = None
    consumer_port = None
    wait_for_provider(address, namespace, service, provider_info["instance_id"], env)
    consumer_port = free_port()
    consumer, consumer_info = start_demo(EXAMPLES / "quickstart/consumer/main.py", [
        "--namespace", namespace,
        "--service", service,
        "--port", str(consumer_port),
        "--call-timeout", "5",
    ], env, "started")
    deadline = time.monotonic() + 10
    body = ""
    while time.monotonic() < deadline:
        try:
            with build_opener(ProxyHandler({})).open(
                f"http://127.0.0.1:{consumer_port}/echo", timeout=10,
            ) as response:
                body = response.read().decode()
                if response.status == 200 and service in body:
                    break
        except OSError:
            pass
        time.sleep(0.5)
    else:
        raise AssertionError(f"quickstart consumer did not return the provider response: {body}")
    if provider.poll() is not None or consumer.poll() is not None:
        raise RuntimeError("quickstart provider or consumer exited during verification")
    return {
        "service": service,
        "provider": provider_info,
        "consumer_port": consumer_port,
        "http_status": 200,
        "effect": "registered, discovered, called, and kept running",
    }


def verify_circuitbreaker(env, address, service_token, namespace):
    caller_service = service_name("circuitbreaker", "caller")
    callee_service = service_name("circuitbreaker", "callee")
    provider, provider_payload = start_demo(FIXTURES / "circuitbreaker_provider.py", [
        "--namespace", namespace,
        "--service", callee_service,
        "--service-token", service_token,
        "--port", "0",
        "--status", "200",
        "--ttl", "3",
    ], env, "registered")
    assert_instance_host(provider_payload["host"], address)
    consumer = None
    consumer_port = None
    wait_for_provider(
        address, namespace, callee_service, provider_payload["registered"], env,
    )
    config = yaml.safe_load(
        (FIXTURES / "config/circuitbreaker/consumer.yaml").read_text(encoding="utf-8")
    )
    circuit = config["consumer"]["circuitBreaker"]
    circuit["checkPeriod"] = "1s"
    circuit["sleepWindow"] = "2s"
    circuit["successCountAfterHalfOpen"] = 2
    circuit["defaultErrorCount"] = 3
    consumer_config = Path(env["POLARIS_DEMO_RUN_DIR"]) / "work/circuitbreaker-consumer.yaml"
    consumer_config.parent.mkdir(parents=True, exist_ok=True)
    consumer_config.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    consumer_port = free_port()
    consumer, consumer_payload = start_demo(FIXTURES / "circuitbreaker_consumer.py", [
        "--namespace", namespace,
        "--service", callee_service,
        "--caller-service", caller_service,
        "--service-token", service_token,
        "--port", str(consumer_port),
        "--call-timeout", "5",
        "--config", str(consumer_config),
    ], env, "started")
    caller_instance_id = consumer_payload.get("caller_instance_id")
    caller_host = consumer_payload.get("host")
    if not caller_instance_id or not caller_host:
        raise RuntimeError("circuitbreaker caller did not register its HTTP endpoint")
    assert_instance_host(caller_host, address)
    wait_for_provider(
        address,
        namespace,
        caller_service,
        caller_instance_id,
        env,
    )
    status, result = wait_for_http(
        f"http://127.0.0.1:{consumer_port}/echo",
        lambda code, body: code == 200 and body["ret_code"] == 200 and body["circuit_state"] == "closed",
    )
    instances_status, instances = request_json(f"http://127.0.0.1:{consumer_port}/instances")
    assert instances_status == 200 and len(instances) == 1
    assert instances[0]["instance_id"] == provider_payload["registered"]

    provider_url = f"http://127.0.0.1:{provider_payload['port']}"
    consumer_url = f"http://127.0.0.1:{consumer_port}"
    wait_for_http(
        f"{provider_url}/switch?openError=true",
        lambda code, body: code == 200 and body["status"] == 500,
    )
    for _ in range(3):
        wait_for_http(
            f"{consumer_url}/echo",
            lambda code, body: code == 500 and body["ret_code"] == 500,
        )
    wait_for_http(
        f"{consumer_url}/instances",
        lambda code, body: code == 200 and body[0]["circuit_state"] == "open",
        timeout=30,
    )
    wait_for_http(
        f"{consumer_url}/instances",
        lambda code, body: code == 200 and body[0]["circuit_state"] == "half_open",
        timeout=30,
    )
    wait_for_http(
        f"{provider_url}/switch?openError=false",
        lambda code, body: code == 200 and body["status"] == 200,
    )
    for _ in range(2):
        wait_for_http(
            f"{consumer_url}/echo",
            lambda code, body: code == 200 and body["ret_code"] == 200,
            timeout=30,
        )
    _, final_instances = wait_for_http(
        f"{consumer_url}/instances",
        lambda code, body: code == 200 and body[0]["circuit_state"] == "closed",
        timeout=30,
    )
    event_names = [
        SDKEventName.CIRCUIT_BREAKER_OPEN,
        SDKEventName.CIRCUIT_BREAKER_HALF_OPEN,
        SDKEventName.CIRCUIT_BREAKER_CLOSE,
    ]
    wait_for_pushed_events(Path(env["POLARIS_DEMO_RUN_DIR"]), event_names)
    if provider.poll() is not None or consumer.poll() is not None:
        raise RuntimeError("circuitbreaker provider or consumer exited during verification")
    return {
        "service": callee_service,
        "services": {
            "caller": caller_service,
            "callee": callee_service,
        },
        "caller": {
            "instance_id": caller_instance_id,
            "host": caller_host,
            "port": consumer_payload["port"],
        },
        "provider": {"instance_id": provider_payload["registered"],
                     "host": provider_payload["host"], "port": provider_payload["port"]},
        "consumer_port": consumer_port,
        "http_status": 200,
        "circuit_state": "closed",
        "circuit_states": ["closed", "open", "half_open", "closed"],
        "reported_events": event_names,
        "final_instances": final_instances,
        "effect": "verified Open, HalfOpen and Close transitions and reported events to Pushgateway",
    }


def verify_discovery_demo(name, env, address, service_token, namespace):
    api_timeout = str(scenario_api_timeout_ms(env))
    scenarios = {
        "sdkconfig/file": (EXAMPLES / "sdkconfig/file/main.py",
                           ["--service", "{service}", "--namespace", namespace,
                            "--timeout", api_timeout],
                           scenario_operation_timeout(env, 90)),
        "sdkconfig/code": (EXAMPLES / "sdkconfig/code/main.py",
                           ["--server", address, "--service", "{service}",
                            "--namespace", namespace, "--timeout", api_timeout],
                           scenario_operation_timeout(env, 90)),
        "cache/expiry": (EXAMPLES / "cache/expiry/main.py",
                         [namespace, "{service}", "--expire-ms", "5000", "--metrics-port", "0"], 90),
        "cache/restart": (EXAMPLES / "cache/restart/main.py",
                          [namespace, "{service}", "--metrics-port", "0"], 90),
        "loadbalancer/random": (EXAMPLES / "loadbalancer/random/main.py",
                                [namespace, "{service}", "2", "--interval", "0"], 90),
        "loadbalancer/wr": (EXAMPLES / "loadbalancer/wr/main.py",
                            [namespace, "{service}", "2", "--interval", "0"], 90),
        "servicerouter": (EXAMPLES / "servicerouter/main.py",
                          [namespace, "{service}", "2", "--interval", "0"], 90),
    }
    script, arguments, timeout = scenarios[name]

    def effect(service, provider_info):
        output = run_demo(
            script,
            [provider_info["instance_id"] if value == "{instance}" else
             service if value == "{service}" else value
             for value in arguments],
            env,
            timeout=timeout,
        )
        if name == "servicerouter":
            selected = [line for line in output.splitlines() if line.startswith("host:")]
            assert len(selected) == 4
            assert provider_info["host"] in output and str(provider_info["port"]) in output
            return {"selected_calls": len(selected),
                    "effect": "discovered and selected provider twice asynchronously and twice synchronously"}
        if name.startswith("loadbalancer/"):
            selected = [line for line in output.splitlines() if line.startswith("host:")]
            assert len(selected) == 4
            assert provider_info["host"] in output and str(provider_info["port"]) in output
            return {"selected_calls": len(selected), "effect": "discovered and selected provider twice asynchronously and twice synchronously"}
        result = last_json(output)
        if name == "sdkconfig/file":
            instances = result["discovery"]["instances"]
            assert instances and instances[0]["id"] == provider_info["instance_id"]
        elif name == "sdkconfig/code":
            instances = result["discovery"]["instances"]
            assert instances and instances[0]["id"] == provider_info["instance_id"]
        elif name == "cache/expiry":
            assert result["initial_ids"] == result["reloaded_ids"] == [provider_info["instance_id"]]
        elif name == "cache/restart":
            assert result["ids"] == [provider_info["instance_id"]]
            backup = Path(env["POLARIS_DEMO_RUN_DIR"]) / "polaris" / "backup" / "restart"
            assert any(backup.glob(cache_backup_glob(namespace, service)))
        return {"result": result, "effect": "discovered provider from the real registry"}

    return with_provider(name, namespace, env, address, service_token, effect)


def verify_multicontext(env, address, service_token, namespace):
    service = service_name("multicontext")
    multienv = env.copy()
    multienv.update(
        POLARIS_FIRST_SERVER=address,
        POLARIS_SECOND_SERVER=address,
        POLARIS_FIRST_SERVICE_TOKEN=service_token,
        POLARIS_SECOND_SERVICE_TOKEN=service_token,
        POLARIS_FIRST_TOKEN=os.getenv("POLARIS_TOKEN", ""),
        POLARIS_SECOND_TOKEN=os.getenv("POLARIS_TOKEN", ""),
    )
    process, result = start_demo(EXAMPLES / "multicontext/main.py", [
        "--namespace", namespace,
        "--service", service,
        "--ttl", "3",
        "--seconds", "4",
        "--keep-running",
    ], multienv, "client_ids", timeout=90)
    assert len(set(result["client_ids"])) == 2
    assert result["first_destroyed"]
    assert result["second_available_after_first_destroy"]
    for instances in result["initial_instances"]:
        for instance in instances:
            assert_instance_host(instance["host"], address)
    if process.poll() is not None:
        raise RuntimeError("multicontext example exited during verification")
    return {
        "service": service,
        "instances": result["initial_instances"],
        "client_ids": result["client_ids"],
        "effect": "registered two instances, verified heartbeats, and kept the process running",
    }


def verify_events(env, address, service_token, namespace):
    def effect(service, provider_info):
        output = run_demo(EXAMPLES / "events/main.py", [
            "--server", address,
            "--namespace", namespace,
            "--service", service,
            "--metrics-port", "0",
        ], env, timeout=90)
        result = last_json(output)
        if result.get("instances", 0) < 1:
            raise AssertionError("Events example did not discover the registered provider")
        if SDKEventName.ON_SERVICE_ADDED not in result.get("events", []):
            raise AssertionError("Events example did not emit OnServiceAdded")
        return {"result": result, "effect": "observed OnServiceAdded from the real registry"}

    return with_provider("events", namespace, env, address, service_token, effect)


def verify_lossless(env, address, service_token, namespace):
    service = service_name("lossless")
    registration_timeout = scenario_timeout(env)
    provider, provider_payload = start_demo(EXAMPLES / "lossless/provider/main.py", [
        "--namespace", namespace,
        "--service", service,
        "--service-token", service_token,
        "--port", "0",
        "--admin-port", "0",
        "--ttl", "3",
    ], env, "instance_id", timeout=registration_timeout)
    assert_instance_host(provider_payload["host"], address)
    status, readiness = wait_for_text(provider_payload["readiness_url"], "REGISTERED", timeout=60)
    if not provider_payload.get("instance_id"):
        raise RuntimeError("lossless provider did not expose its registered instance id")
    wait_for_provider(
        address, namespace, service, provider_payload["instance_id"], env,
    )

    consumer, _ = start_demo(EXAMPLES / "lossless/consumer/main.py", [
        "--namespace", namespace,
        "--service", service,
        "--interval", "0.1",
    ], env, "started", timeout=60)
    time.sleep(3)
    consumer_output = stop_demo(
        consumer, Path(env["POLARIS_DEMO_RUN_DIR"]) / "lossless-consumer.stdout.log", "lossless consumer",
    )
    consumer_result = last_json(consumer_output)
    if not consumer_result.get("calls"):
        raise AssertionError(f"lossless consumer did not invoke the provider: {consumer_result}")
    if provider.poll() is not None:
        raise RuntimeError("lossless provider exited during verification")
    return {
        "service": service,
        "provider": {
            "instance_id": provider_payload["instance_id"],
            "host": provider_payload["host"],
            "port": provider_payload["port"],
        },
        "readiness": readiness,
        "http_status": status,
        "consumer_calls": consumer_result["calls"],
        "kept_running": True,
        "effect": "waited for registry visibility, invoked the provider, and kept it running",
    }


def run_scenario(name, address, service_token, namespace, env):
    aliases = {
        "quickstart/provider": "quickstart",
        "quickstart/consumer": "quickstart",
        "circuitbreaker/provider": "circuitbreaker",
        "circuitbreaker/consumer": "circuitbreaker",
    }
    name = aliases.get(name, name)
    if name == "quickstart":
        return verify_quickstart(env, address, service_token, namespace)
    if name == "circuitbreaker":
        return verify_circuitbreaker(env, address, service_token, namespace)
    if name == "multicontext":
        return verify_multicontext(env, address, service_token, namespace)
    if name == "events":
        return verify_events(env, address, service_token, namespace)
    if name == "lossless":
        return verify_lossless(env, address, service_token, namespace)
    if name == "mcp":
        service = service_name("mcp")
        port = free_port()
        process, result = start_demo(FIXTURES / "mcp.py", [
            "--namespace", namespace, "--service", service, "--server", address,
            "--token", service_token, "--port", str(port),
            "--timeout", str(scenario_api_timeout_ms(env)),
            "--keep-running",
        ], env, "instance_id", timeout=scenario_operation_timeout(env, 90))
        if result["instance_type"] != "Instance":
            raise AssertionError("MCP example did not return an ordinary Instance")
        if set(result["features"]) != {"lookup", "document", "summarize"}:
            raise AssertionError("MCP startup contract does not contain all capabilities")
        assert_instance_host(result["host"], address)
        if process.poll() is not None:
            raise RuntimeError("MCP example exited during verification")
        return {"service": service, **result, "kept_running": True}
    if name == "skill":
        skill_address = os.getenv("POLARIS_SKILL_SERVER_ADDRESS") or default_skill_address(address)
        configured_name = os.getenv("POLARIS_SKILL_NAME", "")
        skill_namespace = resolve_skill_namespace(
            namespace,
            configured_name=configured_name,
            configured_namespace=os.getenv("POLARIS_SKILL_NAMESPACE", ""),
        )
        skill_name = configured_name or discover_skill_name(
            env,
            address,
            skill_address,
            skill_namespace,
            expected_name=E2E_SKILL_FIXTURE_NAME,
        )
        fixture_created = False
        if not skill_name:
            skill_name = create_skill_fixture(address, skill_namespace)
            fixture_created = True
            if not discover_skill_name(
                env,
                address,
                skill_address,
                skill_namespace,
                expected_name=skill_name,
                timeout=60,
                fallback_to_first=False,
            ):
                raise RuntimeError(
                    f"Skill fixture {skill_namespace}/{skill_name} was created "
                    "but did not become readable through the Skill API"
                )
        output = run_demo(FIXTURES / "skill.py", [
            "--skill-server", skill_address,
            "--namespace", skill_namespace,
            "--name", skill_name,
        ], env)
        if not any('"zip_size"' in line for line in output.splitlines()):
            raise AssertionError("Skill example did not finish its download")
        return {
            "skill": skill_name,
            "skill_namespace": skill_namespace,
            "skill_address": skill_address,
            "fixture_created": fixture_created,
            "fixture_reused": not fixture_created,
            "effect": "reused or created the Skill fixture and exercised published Skill download",
        }
    if name == "monitoring":
        service = service_name(name)
        registry_host = address.rsplit(":", 1)[0].strip("[]")
        push_address = f"{registry_host}:9091"
        process, result = start_demo(FIXTURES / "monitoring.py", [
            "--server", address, "--token", service_token, "--namespace", namespace,
            "--service", service, "--mode", "push", "--push-address", push_address,
            "--keep-running",
        ], env, "calls", timeout=120)
        if result.get("mode") != "push" or result.get("calls") != 3:
            raise AssertionError("Real push-mode invocation metrics are missing")
        if result.get("pushes", 0) < 1:
            raise AssertionError("Real Pushgateway export did not complete successfully")
        assert_instance_host(result["host"], address)
        if process.poll() is not None:
            raise RuntimeError("monitoring example exited during verification")
        return {
            "service": service,
            "push_address": push_address,
            **result,
            "kept_running": True,
            "effect": "reported real HTTP call metrics to Pushgateway and kept running",
        }
    if name == "a2a":
        service = service_name(name)
        host = get_local_host(address)
        authority = f"[{host}]" if ":" in host else host
        card = {
            "name": service,
            "description": "Polaris Python A2A integration fixture",
            "version": "1.0.0",
            "supportedInterfaces": [
                {
                    "url": f"http://{authority}:8080/a2a/v1",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "1.0",
                },
                {
                    "url": f"http://{authority}:8080/a2a/legacy",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "0.3",
                },
                {
                    "url": f"http://{authority}:8080/rest",
                    "protocolBinding": "HTTP+JSON",
                    "protocolVersion": "1.0",
                },
            ],
            "capabilities": {"streaming": False},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [{
                "id": "a2a-e2e",
                "name": "A2A E2E",
                "description": "Integration fixture for instance-level AgentCard registration",
                "tags": ["polaris", "a2a", "e2e"],
            }],
        }
        card_path = Path(env["POLARIS_DEMO_RUN_DIR"]) / "work" / "a2a-agent-card.json"
        card_path.parent.mkdir(parents=True, exist_ok=True)
        card_path.write_text(json.dumps(card, indent=2), encoding="utf-8")
        process, result = start_demo(EXAMPLES / "a2a/main.py", [
            "--server", address, "--token", service_token, "--namespace", namespace,
            "--card", str(card_path), "--host", host, "--port", "0",
            "--keep-running",
        ], env, "instance_id", timeout=90)
        if result.get("transport") != "JSONRPC":
            raise AssertionError("A2A metadata discovery failed")
        if result.get("port") != 1 or result.get("protocol") != "":
            raise AssertionError("A2A instance identity does not match registration_port/default protocol")
        expected_endpoint = result.get("endpoint")
        if (
            result.get("a2a_version") != "1.0"
            or not isinstance(expected_endpoint, str)
            or not expected_endpoint.endswith("/a2a/v1")
        ):
            raise AssertionError("A2A AgentCard schema or endpoint was not preserved")
        endpoints = result.get("endpoints")
        if not isinstance(endpoints, dict) or set(endpoints) != {
            "jsonrpc_v1", "jsonrpc_v03", "http_json_v1",
        }:
            raise AssertionError("A2A Provider did not expose all three interfaces")
        calls = {
            "jsonrpc_v1": {
                "jsonrpc": "2.0",
                "id": "v1",
                "method": "SendMessage",
                "params": {"message": {
                    "messageId": "v1-request",
                    "role": "ROLE_USER",
                    "parts": [{"text": "v1"}],
                }},
            },
            "jsonrpc_v03": {
                "jsonrpc": "2.0",
                "id": "v03",
                "method": "message/send",
                "params": {
                    "message": {
                        "kind": "message",
                        "messageId": "v03-request",
                        "role": "user",
                        "parts": [{"kind": "text", "text": "v03"}],
                    },
                },
            },
            "http_json_v1": {
                "message": {
                    "messageId": "rest-request",
                    "role": "ROLE_USER",
                    "parts": [{"text": "rest"}],
                },
            },
        }
        expected_text = {
            "jsonrpc_v1": "A2A 1.0 JSONRPC echo: v1",
            "jsonrpc_v03": "A2A 0.3 JSONRPC echo: v03",
            "http_json_v1": "A2A 1.0 HTTP+JSON echo: rest",
        }
        for interface, payload in calls.items():
            url = endpoints[interface]
            if interface == "http_json_v1":
                url = f"{url.rstrip('/')}/message:send"
            status, body = post_json(url, payload)
            if status != 200:
                raise AssertionError(f"A2A {interface} returned HTTP {status}: {body}")
            if interface != "http_json_v1" and (
                body.get("jsonrpc") != "2.0"
                or body.get("id") != payload["id"]
                or "error" in body
            ):
                raise AssertionError(f"A2A {interface} returned unexpected JSON-RPC response: {body}")
            response = body.get("result") if interface != "http_json_v1" else body
            if interface == "jsonrpc_v03":
                message = response
                if not isinstance(message, dict) or (
                    message.get("kind") != "message" or message.get("role") != "agent"
                ):
                    raise AssertionError(f"A2A {interface} returned unexpected legacy Message: {body}")
            else:
                if not isinstance(response, dict) or set(response) != {"message"}:
                    raise AssertionError(f"A2A {interface} returned unexpected SendMessageResponse: {body}")
                message = response["message"]
                if not isinstance(message, dict) or (
                    "kind" in message
                    or message.get("role") != "ROLE_AGENT"
                    or not message.get("contextId")
                ):
                    raise AssertionError(f"A2A {interface} returned unexpected 1.0 Message: {body}")
            parts = message.get("parts")
            if not message.get("messageId") or not isinstance(parts, list) or not parts:
                raise AssertionError(f"A2A {interface} returned incomplete Message: {body}")
            part = parts[0]
            if not isinstance(part, dict) or (
                interface == "jsonrpc_v03" and part.get("kind") != "text"
            ) or (
                interface != "jsonrpc_v03" and ("kind" in part or "type" in part)
            ):
                raise AssertionError(f"A2A {interface} returned unexpected text part: {body}")
            text = part.get("text")
            if text != expected_text[interface]:
                raise AssertionError(
                    f"A2A {interface} returned unexpected message: {body}")
        assert_instance_host(result["host"], address)
        if process.poll() is not None:
            raise RuntimeError("A2A example exited during verification")
        return {
            "service": service,
            **result,
            "interfaces": sorted(calls),
            "effect": "invoked three A2A interfaces and kept the A2A process running",
        }
    return verify_discovery_demo(name, env, address, service_token, namespace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", required=True)
    args = parser.parse_args()
    try:
        address, service_token = required_environment()
        namespace = e2e_namespace()
        with verification_directory(__file__):
            env = scenario_environment(address)
            result = run_scenario(args.demo, address, service_token, namespace, env)
            assert_event_reporters_enabled(env["POLARIS_DEMO_RUN_DIR"])
            print(json.dumps({"demo": args.demo, "server": address, **result}, sort_keys=True))
        return 0
    except (AssertionError, OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
