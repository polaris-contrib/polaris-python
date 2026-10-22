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

"""Configure the SDK entirely in code without loading a configuration file."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import demo_backup_directory, demo_log_options

import argparse
import json
import os

from polaris import Configuration, ConsumerAPI, ProviderAPI, SDKError, init_context_by_config
from polaris.pkg.model.service import GetInstancesRequest


def create_configuration(server: str = "127.0.0.1:8091") -> Configuration:
    """Assign SDK configuration values directly; durations are integer milliseconds."""
    config = Configuration()
    config.set_default()

    global_config = config.get_global()
    connector = global_config.get_server_connector()
    connector.addresses = [server]
    connector.token = ""
    connector.protocol = "grpc"
    connector.connect_timeout = 1000
    connector.message_time = 3000

    api = global_config.get_api()
    api.bind_ip = "127.0.0.1"
    api.timeout = 5000
    api.max_retry_times = 2
    api.retry_interval = 1000

    global_config.get_stat_reporter().enable = False

    consumer = config.get_consumer()
    consumer.get_local_cache().service_refresh_interval = 5000
    consumer.get_load_balancer().type = "weightedRandom"
    rule = consumer.get_circuit_breaker()
    rule.sleep_window = 15000
    rule.success_count_after_half_open = 2
    rule.default_rule_enable = True
    rule.default_error_count = 5
    rule.default_error_percent = 60
    rule.default_interval = 30000
    rule.default_minimum_request = 20
    return config


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("timeout must be greater than zero")
    return number


def discover(consumer: ConsumerAPI, namespace: str, service: str, timeout: int) -> dict:
    result = consumer.get_instances(
        GetInstancesRequest(namespace=namespace, service=service, timeout=timeout, use_discover_cache=False)
    )
    instances = result.instances
    if not instances:
        raise RuntimeError(f"no instances found for {namespace}/{service}")
    return {
        "namespace": namespace,
        "service": service,
        "instances": [
            {"id": instance.get_id(), "host": instance.get_host(), "port": instance.get_port()}
            for instance in instances
        ],
    }


def main() -> int:
    """Start and destroy one context shared by the SDK APIs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("POLARIS_SERVER_ADDRESS", "127.0.0.1:8091"))
    parser.add_argument("--service", help="optionally discover an existing service")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--timeout", type=positive_int, default=10000)
    args = parser.parse_args()
    try:
        config = create_configuration(args.server)
        config.get_consumer().get_local_cache().persist_dir = str(
            demo_backup_directory(__file__, component="code")
        )
        log_options = demo_log_options(__file__, level="warn", component="code")
        context = init_context_by_config(config, log_options=log_options)
        config = context.get_config()
        try:
            provider = ProviderAPI(context)
            consumer = ConsumerAPI(context)
            for api in (provider, consumer):
                api.check_available()
            global_config = config.get_global()
            connector = global_config.get_server_connector()
            rule = config.get_consumer().get_circuit_breaker()
            result = {
                "source": "code",
                "addresses": connector.get_addresses(),
                "protocol": connector.get_protocol(),
                "token_set": bool(connector.get_token()),
                "connect_timeout_ms": connector.get_connect_timeout(),
                "message_timeout_ms": connector.get_message_timeout(),
                "api_timeout_ms": global_config.get_api().get_timeout(),
                "bind_ip": global_config.get_api().get_bind_ip(),
                "max_retry_times": global_config.get_api().get_max_retry_times(),
                "cache_type": config.get_consumer().get_local_cache().get_type(),
                "service_refresh_interval_ms": config.get_consumer().get_local_cache().get_service_refresh_interval(),
                "loadbalancer": config.get_consumer().get_load_balancer().get_type(),
                "stat_reporter_enabled": global_config.get_stat_reporter().is_enable(),
                "circuit_breaker": {
                    "sleep_window_ms": rule.get_sleep_window(),
                    "success_count_after_half_open": rule.get_success_count_after_half_open(),
                    "default_rule_enable": rule.is_default_rule_enable(),
                    "default_error_count": rule.get_default_error_count(),
                    "default_error_percent": rule.get_default_error_percent(),
                    "default_interval_ms": rule.get_default_interval(),
                    "default_minimum_request": rule.get_default_minimum_request(),
                },
                "shared_context": provider.context is consumer.context,
            }
            if args.service:
                result["discovery"] = discover(consumer, args.namespace, args.service, args.timeout)
        finally:
            context.destroy()
        result["context_destroyed"] = context.is_destroy()
        print(json.dumps(result, sort_keys=True))
        return 0
    except SDKError as exc:
        print(f"SDK error {exc.err_code}: {exc.msg}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
