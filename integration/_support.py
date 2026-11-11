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

"""Runtime configuration and artifact helpers used only by integration fixtures."""

import os
import socket
from pathlib import Path

DEFAULT_E2E_CONNECT_TIMEOUT_MS = 5000
DEFAULT_E2E_MESSAGE_TIMEOUT_MS = 15000
DEFAULT_E2E_API_TIMEOUT_MS = 15000
DEFAULT_E2E_SKILL_TIMEOUT_MS = 30000
DEFAULT_E2E_SKILL_DOWNLOAD_TIMEOUT_MS = 60000


def get_local_host(server_address):
    """Return the local TCP source IP used to reach a Polaris server."""
    from polaris.pkg.model.util import get_ip_from_int_with_port

    host, port = get_ip_from_int_with_port(server_address)
    with socket.create_connection((host, port), timeout=2) as connection:
        return connection.getsockname()[0]


getLocalHost = get_local_host


def demo_polaris_directory(entry):
    """Return the integration run's polaris directory for logs and backups."""
    run = os.getenv("POLARIS_DEMO_RUN_DIR")
    if run:
        return Path(run) / "polaris"
    return Path(entry).resolve().parent / ".logs" / "manual" / "polaris"


def demo_log_options(entry, *, level=None, component=None):
    """Build context log options for a retained integration run."""
    from polaris.api.log import LogOptions

    path = demo_polaris_directory(entry) / "log"
    if component:
        path /= component
    return LogOptions(level=level, log_dir=path)


def demo_backup_directory(entry, *, component=None):
    """Return the inspectable backup directory for an integration run."""
    path = demo_polaris_directory(entry) / "backup"
    if component:
        path /= component
    path.mkdir(parents=True, exist_ok=True)
    return path


def _positive_timeout_env(name, default, env=None):
    environ = os.environ if env is None else env
    raw = environ.get(name, "")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def configure_e2e_event_reporting(config, env=None):
    """Apply integration-only transport overrides and event reporting."""
    environ = os.environ if env is None else env
    config.set_default()
    if environ.get("POLARIS_E2E") == "1":
        connector = config.get_global().get_server_connector()
        connector.connect_timeout = _positive_timeout_env(
            "POLARIS_E2E_CONNECT_TIMEOUT_MS",
            DEFAULT_E2E_CONNECT_TIMEOUT_MS,
            environ,
        )
        connector.message_time = _positive_timeout_env(
            "POLARIS_E2E_MESSAGE_TIMEOUT_MS",
            DEFAULT_E2E_MESSAGE_TIMEOUT_MS,
            environ,
        )
        config.get_global().get_api().timeout = _positive_timeout_env(
            "POLARIS_E2E_API_TIMEOUT_MS",
            DEFAULT_E2E_API_TIMEOUT_MS,
            environ,
        )
        skill_connector = config.get_ai().get_skill().get_server_connector()
        skill_connector.message_timeout = _positive_timeout_env(
            "POLARIS_E2E_SKILL_TIMEOUT_MS",
            DEFAULT_E2E_SKILL_TIMEOUT_MS,
            environ,
        )
        skill_connector.download_timeout = _positive_timeout_env(
            "POLARIS_E2E_SKILL_DOWNLOAD_TIMEOUT_MS",
            DEFAULT_E2E_SKILL_DOWNLOAD_TIMEOUT_MS,
            environ,
        )

    addresses = environ.get("POLARIS_EVENT_REPORTER_ADDRESS", "")
    if not addresses or environ.get("POLARIS_EVENT_REPORTER_ENABLE", "1").lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return config
    reporter = config.get_global().get_event_reporter()
    reporter.enable = True
    reporter.chain = ["pushgateway"]
    pushgateway = reporter.get_pushgateway()
    pushgateway.address = [
        item.strip() for item in addresses.split(",") if item.strip()
    ]
    pushgateway.push_interval = int(
        environ.get("POLARIS_EVENT_REPORTER_PUSH_INTERVAL", "250")
    )
    pushgateway.max_retries = int(
        environ.get("POLARIS_EVENT_REPORTER_MAX_RETRIES", "3")
    )
    pushgateway.retry_interval = int(
        environ.get("POLARIS_EVENT_REPORTER_RETRY_INTERVAL", "100")
    )
    return config
