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

"""Verify YAML and code-based SDK startup without requiring a Polaris server."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2])]
from examples._internal._runtime import verification_directory

import argparse
import json
import os
import subprocess
import textwrap

import yaml

EXAMPLE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXAMPLE_DIR.parents[1]
FILE_DIR = EXAMPLE_DIR / "file"
ENTRY = FILE_DIR / "main.py"
CODE_ENTRY = EXAMPLE_DIR / "code" / "main.py"
ONLY = None
CASE_COUNT = 0

# Replace the TCP probe and client-report RPC, leaving SDK startup logic intact.
OFFLINE_RUNNER = textwrap.dedent("""\
    import os
    import runpy
    import sys
    import socket
    from contextlib import ExitStack
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import patch
    from polarismesh_specification.api.v1.service_manage import response_pb2

    reported_hosts = []

    async def report_client(self, request):
        reported_hosts.append(request.host.value)
        expected = os.environ.get("POLARIS_EXAMPLE_EXPECTED_BIND_IP")
        if expected is not None:
            assert request.host.value == expected, request.host.value
        response = response_pb2.Response()
        response.code.value = 200000
        return response

    probes = []
    writers = []

    class ProbeWriter:
        def __init__(self):
            self.closed = False

        def get_extra_info(self, name):
            assert name == "sockname"
            return ("192.0.2.10", 1234)

        def close(self):
            self.closed = True

        async def wait_closed(self):
            pass

    async def open_connection(host, port):
        probes.append([host, port])
        if os.environ.get("POLARIS_EXAMPLE_SKIP_IP_PROBE"):
            raise AssertionError("explicit SDK address must skip the TCP probe")
        if os.environ.get("POLARIS_EXAMPLE_IP_PROBE_FAIL"):
            raise OSError("offline probe failure")
        writer = ProbeWriter()
        writers.append(writer)
        return None, writer

    sys.argv = sys.argv[1:]
    with ExitStack() as stack:
        stack.enter_context(patch("pathlib.Path.home", return_value=Path(os.environ["POLARIS_EXAMPLE_HOME"])))
        stack.enter_context(patch(
            "polaris.plugin.server_connector.grpc_connector.connection.GrpcConnection.report_client", report_client
        ))
        stack.enter_context(patch("polaris.pkg.model.util.asyncio.open_connection", open_connection))
        stack.enter_context(patch("polaris.pkg.model.util.psutil.net_if_addrs", return_value={
            "test0": [SimpleNamespace(family=socket.AF_INET, address="192.0.2.20")],
        }))
        if os.environ.get("POLARIS_EXAMPLE_CODE"):
            for name in ("load_config_file", "find_default_config_file"):
                stack.enter_context(patch(
                    "polaris.pkg.config.loader." + name,
                    side_effect=AssertionError("code configuration must not read configuration files"),
                ))
        try:
            runpy.run_path(sys.argv[0], run_name="__main__")
        except SystemExit as error:
            if error.code not in (None, 0):
                raise
    if os.environ.get("POLARIS_EXAMPLE_SKIP_IP_PROBE"):
        assert not probes
    expected = os.environ.get("POLARIS_EXAMPLE_PROBE_TARGET")
    if expected:
        import json
        assert probes == [json.loads(expected)], probes
    assert all(writer.closed for writer in writers)
    expected = os.environ.get("POLARIS_EXAMPLE_EXPECTED_BIND_IP")
    if expected is not None:
        assert all(host == expected for host in reported_hosts), reported_hosts
""")


def run_example(cwd: Path, args: list[str], env: dict[str, str], entry: Path = ENTRY) -> subprocess.CompletedProcess:
    """Run the real example in a fresh process with isolated environment and runtime files."""
    global CASE_COUNT
    CASE_COUNT += 1
    run = Path(os.environ["POLARIS_DEMO_RUN_DIR"]) / "cases" / f"{entry.parent.name}-{CASE_COUNT:02d}"
    run.mkdir(parents=True)
    process_env = {key: value for key, value in os.environ.items() if not key.startswith("POLARIS_")}
    process_env["POLARIS_DEMO_RUN_DIR"] = str(run)
    process_env["POLARIS_DEMO_DIRECTORY"] = os.environ["POLARIS_DEMO_DIRECTORY"]
    process_env["POLARIS_EXAMPLE_HOME"] = str(cwd / "home")
    if entry == CODE_ENTRY:
        process_env["POLARIS_EXAMPLE_CODE"] = "1"
    paths = [str(REPO_ROOT / "src"), str(REPO_ROOT), process_env.get("PYTHONPATH", "")]
    process_env["PYTHONPATH"] = os.pathsep.join(path for path in paths if path)
    process_env.update(env)
    completed = subprocess.run(
        [sys.executable, "-c", OFFLINE_RUNNER, str(entry), *args],
        cwd=cwd,
        env=process_env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    (run / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (run / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    return completed


def verify_success(
    cwd: Path, name: str, args: list[str], expected: dict,
    env: dict[str, str] | None = None, entry: Path = ENTRY,
) -> None:
    """Require successful startup, expected effective values, shared APIs, and cleanup."""
    if ONLY and entry.parent.name != ONLY:
        return
    completed = run_example(cwd, args, env or {}, entry)
    if completed.returncode != 0:
        raise RuntimeError(f"{name}: exit {completed.returncode}\n{completed.stderr}")
    result = json.loads(completed.stdout)
    expected = {**expected, "shared_context": True, "context_destroyed": True}
    for key, value in expected.items():
        if result.get(key) != value:
            raise RuntimeError(f"{name}: {key}: expected {value!r}, got {result.get(key)!r}")
    print(f"PASS {name}")


def verify_failure(cwd: Path, name: str, args: list[str], message: str, env: dict[str, str] | None = None) -> None:
    """Require configuration errors to produce a nonzero exit and a clear diagnostic."""
    if ONLY == "code":
        return
    completed = run_example(cwd, args, env or {})
    if completed.returncode != 1 or message not in completed.stderr:
        raise RuntimeError(f"{name}: unexpected exit or diagnostic\n{completed.stderr}")
    print(f"PASS {name}")


def main() -> int:
    """Verify YAML loading, default lookup, environment expansion, and code-only startup."""
    global ONLY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("code", "file"), help="verify one SDK configuration demo")
    ONLY = parser.parse_args().only
    expected = {
        "addresses": ["127.0.0.1:8091"],
        "protocol": "grpc",
        "token_set": False,
        "connect_timeout_ms": 1000,
        "message_timeout_ms": 3000,
        "api_timeout_ms": 5000,
        "bind_ip": "127.0.0.1",
        "max_retry_times": 2,
        "cache_type": "inmemory",
        "service_refresh_interval_ms": 5000,
        "loadbalancer": "weightedRandom",
        "stat_reporter_enabled": False,
        "circuit_breaker": {
            "sleep_window_ms": 30000, "success_count_after_half_open": 3, "default_rule_enable": True,
            "default_error_count": 10, "default_error_percent": 50, "default_interval_ms": 60000,
            "default_minimum_request": 10,
        },
    }
    literal_expected = {
        **expected,
        "addresses": ["${POLARIS_SERVER_ADDRESS:127.0.0.1:8091}"],
    }
    default_clusters = {
        "discoverCluster": {"namespace": "", "service": "", "refresh_interval_ms": 60000},
        "healthCheckCluster": {"namespace": "", "service": "", "refresh_interval_ms": 60000},
        "monitorCluster": {"namespace": "Polaris", "service": "polaris.monitor", "refresh_interval_ms": 60000},
    }
    try:
        with verification_directory(__file__) as directory:
            cwd = Path(directory)
            verify_success(
                cwd, "explicit polaris.yaml file",
                ["--config", str(FILE_DIR / "polaris.yaml"), "--no-env"], literal_expected,
                {"POLARIS_EXAMPLE_SKIP_IP_PROBE": "1", "POLARIS_EXAMPLE_EXPECTED_BIND_IP": "127.0.0.1"},
            )
            verify_success(cwd, "adjacent example file", ["--no-env"], literal_expected)
            rule_yaml = cwd / "rule.yaml"
            rule_config = yaml.safe_load((FILE_DIR / "polaris.yaml").read_text(encoding="utf-8"))
            rule_config["consumer"]["circuitBreaker"] = {
                "sleepWindow": "15s", "successCountAfterHalfOpen": 2, "defaultRuleEnable": True,
                "defaultErrorCount": 5, "defaultErrorPercent": 60, "defaultInterval": "30s",
                "defaultMinimumRequest": 20,
            }
            rule_expected = {
                "sleep_window_ms": 15000, "success_count_after_half_open": 2, "default_rule_enable": True,
                "default_error_count": 5, "default_error_percent": 60, "default_interval_ms": 30000,
                "default_minimum_request": 20,
            }
            rule_yaml.write_text(yaml.safe_dump(rule_config), encoding="utf-8")
            verify_success(cwd, "configured local instance circuit rule", ["--config", str(rule_yaml), "--no-env"],
                           {**literal_expected, "circuit_breaker": rule_expected})
            rule_config["consumer"]["circuitBreaker"]["defaultRuleEnable"] = False
            rule_yaml.write_text(yaml.safe_dump(rule_config), encoding="utf-8")
            verify_success(cwd, "disabled default instance circuit rule", ["--config", str(rule_yaml), "--no-env"],
                           {**literal_expected, "circuit_breaker": {**rule_expected, "default_rule_enable": False}})
            rule_config["consumer"]["circuitBreaker"]["defaultInterval"] = "${APP_BREAKER_WINDOW:45s}"
            rule_yaml.write_text(yaml.safe_dump(rule_config), encoding="utf-8")
            verify_success(cwd, "local circuit rule duration placeholder", ["--config", str(rule_yaml)],
                           {**expected, "circuit_breaker": {**rule_expected, "default_rule_enable": False,
                                                          "default_interval_ms": 20000}},
                           {"APP_BREAKER_WINDOW": "20s"})
            verify_success(
                cwd, "complete configuration reference",
                ["--config", str(REPO_ROOT / "docs" / "config" / "polaris.yaml"), "--no-env"],
                {
                    **expected, "connect_timeout_ms": 500, "message_timeout_ms": 1500,
                    "api_timeout_ms": 1000, "max_retry_times": 1,
                    "service_refresh_interval_ms": 2000, "stat_reporter_enabled": True,
                    "bind_ip": "192.0.2.10",
                    "system_clusters": default_clusters,
                },
                {"POLARIS_EXAMPLE_PROBE_TARGET": '["127.0.0.1", 8091]',
                 "POLARIS_EXAMPLE_EXPECTED_BIND_IP": "192.0.2.10"},
            )

            automatic_yaml = cwd / "automatic.yaml"
            automatic_config = yaml.safe_load((FILE_DIR / "polaris.yaml").read_text(encoding="utf-8"))
            automatic_config["global"]["api"].pop("bindIP")
            automatic_config["global"]["serverConnector"]["addresses"] = ["registry.example:8091", "other:8092"]
            automatic_yaml.write_text(yaml.safe_dump(automatic_config), encoding="utf-8")
            automatic_expected = {**expected, "addresses": ["registry.example:8091", "other:8092"]}
            verify_success(
                cwd, "automatic SDK IP from first configured server", ["--config", str(automatic_yaml), "--no-env"],
                {**automatic_expected, "bind_ip": "192.0.2.10"},
                {"POLARIS_EXAMPLE_PROBE_TARGET": '["registry.example", 8091]',
                 "POLARIS_EXAMPLE_EXPECTED_BIND_IP": "192.0.2.10"},
            )
            verify_success(
                cwd, "failed SDK IP probe preserves startup and empty address",
                ["--config", str(automatic_yaml), "--no-env"], {**automatic_expected, "bind_ip": ""},
                {"POLARIS_EXAMPLE_IP_PROBE_FAIL": "1", "POLARIS_EXAMPLE_EXPECTED_BIND_IP": ""},
            )
            automatic_config["global"]["api"]["bindIf"] = "test0"
            automatic_yaml.write_text(yaml.safe_dump(automatic_config), encoding="utf-8")
            verify_success(
                cwd, "SDK IP from named interface without TCP probe",
                ["--config", str(automatic_yaml), "--no-env"], {**automatic_expected, "bind_ip": "192.0.2.20"},
                {"POLARIS_EXAMPLE_SKIP_IP_PROBE": "1", "POLARIS_EXAMPLE_EXPECTED_BIND_IP": "192.0.2.20"},
            )
            automatic_config["global"]["api"]["bindIP"] = "192.0.2.30"
            automatic_config["global"]["api"]["bindIf"] = "missing"
            automatic_yaml.write_text(yaml.safe_dump(automatic_config), encoding="utf-8")
            verify_success(
                cwd, "explicit SDK IP overrides invalid interface",
                ["--config", str(automatic_yaml), "--no-env"], {**automatic_expected, "bind_ip": "192.0.2.30"},
                {"POLARIS_EXAMPLE_SKIP_IP_PROBE": "1", "POLARIS_EXAMPLE_EXPECTED_BIND_IP": "192.0.2.30"},
            )
            automatic_config["global"]["api"].pop("bindIP")
            automatic_yaml.write_text(yaml.safe_dump(automatic_config), encoding="utf-8")
            verify_failure(
                cwd, "missing named interface rejects startup",
                ["--config", str(automatic_yaml), "--no-env"], "provided bind interface missing",
            )

            clusters_yaml = cwd / "clusters.yaml"
            clusters_config = yaml.safe_load((FILE_DIR / "polaris.yaml").read_text(encoding="utf-8"))
            clusters_config["global"]["system"] = {
                name: {"namespace": "custom", "service": name, "refreshInterval": "10m"}
                for name in default_clusters
            }
            clusters_yaml.write_text(yaml.safe_dump(clusters_config), encoding="utf-8")
            verify_success(
                cwd, "Java Go system cluster hierarchy", ["--config", str(clusters_yaml), "--no-env"],
                {**literal_expected, "system_clusters": {
                    name: {"namespace": "custom", "service": name, "refresh_interval_ms": 600000}
                    for name in default_clusters
                }},
            )

            custom = cwd / "custom.yaml"
            data = yaml.safe_load((FILE_DIR / "polaris.yaml").read_text(encoding="utf-8"))
            data["global"]["serverConnector"]["token"] = "file-token"
            custom.write_text(yaml.safe_dump(data), encoding="utf-8")
            custom_expected = {**expected, "token_set": True}
            custom_no_env_expected = {**literal_expected, "token_set": True}
            overrides = {
                "POLARIS_NAMESPACE": "env-namespace",
                "POLARIS_SERVER": "127.0.0.1:8092,127.0.0.1:8093",
                "POLARIS_LOG_LEVEL": "ERROR",
            }
            verify_success(
                cwd, "environment overrides preserve file values", ["--config", str(custom)],
                {
                    **custom_expected,
                    "addresses": ["127.0.0.1:8092", "127.0.0.1:8093"],
                },
                overrides,
            )
            verify_success(
                cwd, "explicit file without environment overrides", ["--config", str(custom), "--no-env"],
                custom_no_env_expected, overrides,
            )
            verify_success(
                cwd, "POLARIS_CONFIG_FILE lookup", ["--default"], custom_expected,
                {"POLARIS_CONFIG_FILE": str(custom)},
            )

            local_yaml = cwd / "polaris.yaml"
            local_yaml.write_text(custom.read_text(encoding="utf-8"), encoding="utf-8")
            verify_success(cwd, "current directory polaris.yaml lookup", ["--default"], custom_expected)
            local_yaml.unlink()

            home_config = cwd / "home" / ".config" / "polaris" / "polaris.yaml"
            home_config.parent.mkdir(parents=True)
            home_config.write_text(custom.read_text(encoding="utf-8"), encoding="utf-8")
            verify_success(cwd, "user configuration directory lookup", ["--default"], custom_expected)
            verify_success(
                cwd, "explicit environment path takes precedence", ["--default"], expected,
                {"POLARIS_CONFIG_FILE": str(FILE_DIR / "polaris.yaml")},
            )
            home_config.unlink()

            placeholders = cwd / "provider.yaml"
            provider_config = yaml.safe_load((FILE_DIR / "polaris.yaml").read_text(encoding="utf-8"))
            provider_config["global"]["serverConnector"]["addresses"] = ["${POLARIS_SERVER}:8091"]
            provider_config["global"]["serverConnector"]["token"] = "${POLARIS_TOKEN}"
            placeholders.write_text(yaml.safe_dump(provider_config), encoding="utf-8")
            verify_success(
                cwd, "Go provider placeholders and duration",
                ["--config", str(placeholders)], {**expected, "addresses": ["127.0.0.2:8091"], "token_set": True},
                {"POLARIS_SERVER": "127.0.0.2", "POLARIS_TOKEN": "provider-token"},
            )
            verify_success(
                cwd, "full endpoint override of Go provider placeholder", ["--config", str(placeholders)],
                {**expected, "addresses": ["127.0.0.3:8092"], "token_set": True},
                {"POLARIS_SERVER": "127.0.0.2", "POLARIS_SERVER_ADDRESS": "127.0.0.3:8092", "POLARIS_TOKEN": "token"},
            )
            provider_config["global"]["serverConnector"]["addresses"] = [
                "${POLARIS_SERVER_ADDRESS:127.0.0.1:8091}"
            ]
            placeholders.write_text(yaml.safe_dump(provider_config), encoding="utf-8")
            verify_success(
                cwd, "placeholder default when address environment is empty", ["--config", str(placeholders)],
                expected, {"POLARIS_SERVER_ADDRESS": ""},
            )
            verify_success(
                cwd, "placeholder environment overrides default", ["--config", str(placeholders)],
                {**expected, "addresses": ["127.0.0.4:8092"]},
                {"POLARIS_SERVER_ADDRESS": "127.0.0.4:8092"},
            )

            missing = cwd / "missing.yaml"
            verify_failure(
                cwd, "missing explicit file", ["--config", str(missing), "--no-env"],
                "Configuration file not found",
            )
            verify_failure(
                cwd, "missing POLARIS_CONFIG_FILE does not fall back", ["--default"],
                "Configuration file not found", {"POLARIS_CONFIG_FILE": str(missing)},
            )
            invalid = cwd / "invalid.yaml"
            invalid.write_text("global: [invalid", encoding="utf-8")
            verify_failure(cwd, "malformed YAML", ["--config", str(invalid), "--no-env"], "Failed to parse")
            invalid.write_text(
                "global:\n  serverConnector:\n    address: [127.0.0.1:8091]\n", encoding="utf-8",
            )
            verify_failure(
                cwd, "unknown configuration key", ["--config", str(invalid), "--no-env"],
                "Unknown configuration keys",
            )
            removed_sections = {
                "removed root namespace": {"namespace": "default"},
                "removed system log path": {"global": {"system": {"logPath": "./polaris.log"}}},
                "removed system log level": {"global": {"system": {"logLevel": "warn"}}},
                "removed stat reporter addresses": {"global": {"statReporter": {"addresses": []}}},
                "derived API bind IP": {"global": {"api": {"bindIPValue": "127.0.0.1"}}},
            }
            for name, section in removed_sections.items():
                invalid.write_text(yaml.safe_dump(section), encoding="utf-8")
                verify_failure(
                    cwd, name, ["--config", str(invalid), "--no-env"], "Unknown configuration keys",
                )
            unsupported = cwd / "polaris.json"
            unsupported.write_text("{}", encoding="utf-8")
            verify_failure(
                cwd, "unsupported file format", ["--config", str(unsupported), "--no-env"],
                "Only .yaml configuration files are supported",
            )
            verify_failure(
                cwd, "invalid environment value", ["--config", str(custom)],
                "POLARIS_TIMEOUT must be an integer", {"POLARIS_TIMEOUT": "invalid"},
            )
            code_expected = {**expected, "source": "code", "circuit_breaker": rule_expected}
            verify_success(cwd, "code-only startup without files", [], code_expected, entry=CODE_ENTRY)
            local_yaml.write_text("invalid: [yaml", encoding="utf-8")
            verify_success(
                cwd, "code-only startup ignores files and environment", [], code_expected,
                {"POLARIS_CONFIG_FILE": str(missing), "POLARIS_SERVER": "env-server:8091", "POLARIS_TIMEOUT": "invalid"},
                entry=CODE_ENTRY,
            )
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    print("All YAML and code startup checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
