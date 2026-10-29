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
import select
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
from urllib.request import ProxyHandler, build_opener

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples"

sys.path[:0] = [str(REPO / "src"), str(REPO)]
from examples._internal._runtime import (
    configure_e2e_event_reporting,
    get_local_host,
    record_external_process,
    verification_directory,
)
from polaris import Configuration, ConsumerAPI, SDKEventName, init_context_by_config
from polaris.api.log import LogOptions
from polaris.pkg.model.error import SDKError
from polaris.pkg.model.service import GetInstancesRequest


def required_environment():
    address = os.getenv("POLARIS_SERVER_ADDRESS") or os.getenv("POLARIS_SERVER_ADDRESSES")
    if not address:
        raise RuntimeError("POLARIS_SERVER_ADDRESS is required for real-service verification")
    address = address.split(",", 1)[0].strip()
    service_token = os.getenv("POLARIS_E2E_SERVICE_TOKEN") or os.getenv("POLARIS_SERVICE_TOKEN")
    if not service_token:
        raise RuntimeError(
            "POLARIS_SERVICE_TOKEN or POLARIS_E2E_SERVICE_TOKEN is required to register test instances"
        )
    return address, service_token


def scenario_environment(address):
    env = os.environ.copy()
    registry_host = address.rsplit(":", 1)[0].strip("[]")
    env.update(
        POLARIS_E2E="1",
        POLARIS_SERVER_ADDRESS=address,
        POLARIS_SERVER=address,
        POLARIS_SERVER_ADDRESSES=address,
        POLARIS_EVENT_REPORTER_ENABLE="1",
        POLARIS_EVENT_REPORTER_ADDRESS=f"{registry_host}:9091",
        POLARIS_EVENT_REPORTER_PUSH_INTERVAL="250",
        POLARIS_EVENT_REPORTER_MAX_RETRIES="3",
        POLARIS_EVENT_REPORTER_RETRY_INTERVAL="100",
        PYTHONUNBUFFERED="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [
        str(REPO / "src"), str(REPO), env.get("PYTHONPATH", ""),
    ]))
    return env


def e2e_namespace():
    """Return the namespace for services created by real-service verification."""
    return os.getenv("POLARIS_E2E_NAMESPACE", "python-integration")


def service_name(scenario):
    """Build a service name from the demo path and the local time to milliseconds."""
    label = scenario.strip("/").replace("/", "-")
    now = datetime.now()
    stamp = now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"
    return f"polaris-python-e2e-{label}-{stamp}"


def assert_instance_host(actual, address):
    """Require the advertised instance IP to match the Polaris route source IP."""
    expected = get_local_host(address)
    if actual != expected:
        raise AssertionError(f"instance host {actual!r} does not match local route IP {expected!r}")


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


def start_demo(script, arguments, env, expected_key, timeout=20):
    run_dir = Path(env["POLARIS_DEMO_RUN_DIR"])
    output_path = run_dir / f"{script.parent.name}.stdout.log"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, str(script), *arguments],
            cwd=script.parent,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
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
            if expected_key in value:
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
    output = "".join(getattr(process, "demo_lines", [])) + output
    Path(log_path).write_text(output, encoding="utf-8")
    if process.returncode != 0:
        raise RuntimeError(f"{description} exited with {process.returncode}:\n{output}")
    return output


def run_demo(script, arguments, env, timeout=30):
    completed = subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=script.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output_path = Path(env["POLARIS_DEMO_RUN_DIR"]) / f"{script.parent.name}.stdout.log"
    output_path.write_text(completed.stdout, encoding="utf-8")
    (output_path.parent / f"{script.parent.name}.stderr.log").write_text(completed.stderr, encoding="utf-8")
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


def request_text(url):
    try:
        with build_opener(ProxyHandler({})).open(url, timeout=10) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        with error:
            return error.code, error.read().decode("utf-8", errors="replace")


def wait_for_text(url, expected, timeout=10):
    deadline = time.monotonic() + timeout
    last_value = ""
    while time.monotonic() < deadline:
        status, last_value = request_text(url)
        if status == 200 and last_value == expected:
            return status, last_value
        time.sleep(0.2)
    raise RuntimeError(f"HTTP endpoint {url} did not return {expected!r}: {last_value!r}")


def wait_for_provider(address, namespace, service, expected_id, env, timeout=20):
    run = Path(env["POLARIS_DEMO_RUN_DIR"])
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        config = Configuration()
        config.set_default()
        config.get_global().get_admin().port = 0
        connector = config.get_global().get_server_connector()
        connector.addresses = [address]
        connector.token = os.getenv("POLARIS_TOKEN", "")
        connector.connect_timeout = 2000
        connector.message_time = 3000
        config.get_global().get_api().bind_ip = "127.0.0.1"
        config.get_global().get_api().timeout = 3000
        config.get_consumer().get_local_cache().persist_dir = str(run / "polaris" / "backup" / "probe")
        configure_e2e_event_reporting(config)
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
                        timeout=3000,
                        use_discover_cache=False,
                    )
                )
                return [instance.get_id() for instance in result.get_instances()]

            ids = asyncio.run(asyncio.wait_for(discover(), timeout=5))
            if expected_id in ids:
                return
            last_error = AssertionError(f"instance {expected_id} not visible; got {ids}")
        except (AssertionError, OSError, SDKError, TimeoutError, RuntimeError) as error:
            last_error = error
        finally:
            context.destroy()
        time.sleep(0.5)
    raise RuntimeError(f"service {namespace}/{service} did not become visible: {last_error}")


def wait_for_http(url, predicate, timeout=10):
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


def wait_for_pushed_events(run, event_names, timeout=10):
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
    service = service_name("circuitbreaker")
    provider, provider_payload = start_demo(EXAMPLES / "circuitbreaker/provider/main.py", [
        "--namespace", namespace,
        "--service", service,
        "--service-token", service_token,
        "--port", "0",
        "--status", "200",
        "--ttl", "3",
    ], env, "registered")
    assert_instance_host(provider_payload["host"], address)
    consumer = None
    consumer_port = None
    wait_for_provider(
        address, namespace, service, provider_payload["registered"], env,
    )
    config = yaml.safe_load(
        (EXAMPLES / "circuitbreaker/consumer/polaris.yaml").read_text(encoding="utf-8")
    )
    circuit = config["consumer"]["circuitBreaker"]
    circuit["checkPeriod"] = "1s"
    circuit["sleepWindow"] = "2s"
    circuit["successCountAfterHalfOpen"] = 2
    circuit["defaultErrorCount"] = 3
    consumer_config = Path(env["POLARIS_DEMO_RUN_DIR"]) / "work/circuitbreaker-consumer.yaml"
    consumer_config.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    consumer_port = free_port()
    consumer, _ = start_demo(EXAMPLES / "circuitbreaker/consumer/main.py", [
        "--namespace", namespace,
        "--service", service,
        "--port", str(consumer_port),
        "--call-timeout", "5",
        "--config", str(consumer_config),
    ], env, "started")
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
        timeout=10,
    )
    wait_for_http(
        f"{consumer_url}/instances",
        lambda code, body: code == 200 and body[0]["circuit_state"] == "half_open",
        timeout=10,
    )
    wait_for_http(
        f"{provider_url}/switch?openError=false",
        lambda code, body: code == 200 and body["status"] == 200,
    )
    for _ in range(2):
        wait_for_http(
            f"{consumer_url}/echo",
            lambda code, body: code == 200 and body["ret_code"] == 200,
            timeout=10,
        )
    _, final_instances = wait_for_http(
        f"{consumer_url}/instances",
        lambda code, body: code == 200 and body[0]["circuit_state"] == "closed",
        timeout=10,
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
        "service": service,
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
    scenarios = {
        "sdkconfig/file": (EXAMPLES / "sdkconfig/file/main.py",
                           ["--service", "{service}", "--namespace", namespace, "--timeout", "5000"], 30),
        "sdkconfig/code": (EXAMPLES / "sdkconfig/code/main.py",
                           ["--server", address, "--service", "{service}",
                            "--namespace", namespace, "--timeout", "5000"], 30),
        "cache/expiry": (EXAMPLES / "cache/expiry/main.py",
                         [namespace, "{service}", "--expire-ms", "5000", "--metrics-port", "0"], 30),
        "cache/restart": (EXAMPLES / "cache/restart/main.py",
                          [namespace, "{service}", "--metrics-port", "0"], 30),
        "loadbalancer/random": (EXAMPLES / "loadbalancer/random/main.py",
                                [namespace, "{service}", "2", "--interval", "0"], 30),
        "loadbalancer/wr": (EXAMPLES / "loadbalancer/wr/main.py",
                            [namespace, "{service}", "2", "--interval", "0"], 30),
        "servicerouter": (EXAMPLES / "servicerouter/main.py",
                          [namespace, "{service}", "2", "--interval", "0"], 30),
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
    ], multienv, "client_ids", timeout=30)
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
    service = service_name("events")

    def effect(service, provider_info):
        output = run_demo(EXAMPLES / "events/main.py", [
            "--server", address,
            "--namespace", namespace,
            "--service", service,
            "--metrics-port", "0",
        ], env, timeout=30)
        result = last_json(output)
        if result.get("instances", 0) < 1:
            raise AssertionError("Events example did not discover the registered provider")
        if SDKEventName.ON_SERVICE_ADDED not in result.get("events", []):
            raise AssertionError("Events example did not emit OnServiceAdded")
        return {"result": result, "effect": "observed OnServiceAdded from the real registry"}

    return with_provider("events", namespace, env, address, service_token, effect)


def verify_lossless(env, address, service_token, namespace):
    service = service_name("lossless")
    provider, provider_payload = start_demo(EXAMPLES / "lossless/provider/main.py", [
        "--namespace", namespace,
        "--service", service,
        "--service-token", service_token,
        "--port", "0",
        "--admin-port", "0",
        "--ttl", "3",
    ], env, "started", timeout=30)
    assert_instance_host(provider_payload["host"], address)
    status, readiness = wait_for_text(provider_payload["readiness_url"], "REGISTERED", timeout=15)

    consumer, _ = start_demo(EXAMPLES / "lossless/consumer/main.py", [
        "--namespace", namespace,
        "--service", service,
        "--interval", "0.1",
    ], env, "started", timeout=20)
    time.sleep(1)
    consumer_output = stop_demo(
        consumer, Path(env["POLARIS_DEMO_RUN_DIR"]) / "lossless-consumer.stdout.log", "lossless consumer",
    )
    consumer_result = last_json(consumer_output)
    if not consumer_result.get("calls"):
        raise AssertionError(f"lossless consumer did not invoke the provider: {consumer_result}")

    provider_output = stop_demo(
        provider, Path(env["POLARIS_DEMO_RUN_DIR"]) / "lossless-provider.stdout.log", "lossless provider",
    )
    deregistered = [json.loads(line) for line in provider_output.splitlines()
                    if line.startswith("{") and "deregistered" in line]
    if not deregistered:
        raise AssertionError(f"lossless provider did not report deregistration: {provider_output}")
    return {
        "service": service,
        "provider": {"host": provider_payload["host"], "port": provider_payload["port"]},
        "readiness": readiness,
        "http_status": status,
        "consumer_calls": consumer_result["calls"],
        "deregistered": deregistered[0]["deregistered"],
        "effect": "waited for readiness, invoked the provider, and deregistered losslessly",
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
        process, result = start_demo(EXAMPLES / "mcp/main.py", [
            "--namespace", namespace, "--service", service, "--server", address,
            "--token", service_token, "--port", str(port),
            "--keep-running",
        ], env, "instance_id", timeout=30)
        if result["instance_type"] != "Instance":
            raise AssertionError("MCP example did not return an ordinary Instance")
        if set(result["features"]) != {"lookup", "document", "summarize"}:
            raise AssertionError("MCP startup contract does not contain all capabilities")
        assert_instance_host(result["host"], address)
        if process.poll() is not None:
            raise RuntimeError("MCP example exited during verification")
        return {"service": service, **result, "kept_running": True}
    if name == "skill":
        skill_address = os.getenv("POLARIS_SKILL_SERVER_ADDRESS")
        skill_name = os.getenv("POLARIS_SKILL_NAME")
        if not skill_address or not skill_name:
            raise RuntimeError("Skill verification requires POLARIS_SKILL_SERVER_ADDRESS and POLARIS_SKILL_NAME")
        output = run_demo(EXAMPLES / "skill/main.py", ["--skill-server", skill_address, "--name", skill_name], env)
        if not any('"zip_size"' in line for line in output.splitlines()):
            raise AssertionError("Skill example did not finish its download")
        return {"skill": skill_name, "effect": "queried and downloaded an existing published Skill"}
    if name == "monitoring":
        service = service_name(name)
        registry_host = address.rsplit(":", 1)[0].strip("[]")
        push_address = f"{registry_host}:9091"
        output = run_demo(EXAMPLES / "monitoring/main.py", [
            "--server", address, "--token", service_token, "--namespace", namespace,
            "--service", service, "--mode", "push", "--push-address", push_address,
        ], env, timeout=90)
        result = last_json(output)
        if result.get("mode") != "push" or result.get("calls") != 3:
            raise AssertionError("Real push-mode invocation metrics are missing")
        if result.get("pushes", 0) < 1:
            raise AssertionError("Real Pushgateway export did not complete successfully")
        assert_instance_host(result["host"], address)
        return {
            "service": service,
            "push_address": push_address,
            **result,
            "effect": "reported real HTTP call metrics to Pushgateway and explicitly deregistered",
        }
    if name in ("a2a", "monitoring"):
        service = service_name(name)
        output = run_demo(EXAMPLES / name / "main.py", [
            "--server", address, "--token", service_token, "--namespace", namespace,
            "--service", service,
        ], env, timeout=90)
        result = last_json(output)
        if name == "a2a" and result.get("transport") != "JSONRPC":
            raise AssertionError("A2A metadata discovery failed")
        if name == "a2a":
            assert_instance_host(result["host"], address)
        return {"service": service, **result, "effect": "verified and explicitly deregistered"}
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
            print(json.dumps({"demo": args.demo, "server": address, **result}, sort_keys=True))
        return 0
    except (AssertionError, OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
