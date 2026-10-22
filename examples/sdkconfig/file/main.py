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

"""Start the SDK from a local configuration file and optionally discover a service."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import demo_backup_directory, demo_log_options

import argparse
import json

from polaris import ConsumerAPI, Configuration, ProviderAPI, SDKContext, SDKError, init_context_by_config
from polaris.pkg.model.service import GetInstancesRequest


def positive_int(value: str) -> int:
    """Parse a positive timeout in milliseconds."""
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("timeout must be greater than zero")
    return number


def parse_args() -> argparse.Namespace:
    """Parse file selection and optional service discovery arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--config", type=Path, help="YAML file; defaults to the adjacent polaris.yaml")
    source.add_argument("--default", action="store_true", help="use SDK default file lookup")
    parser.add_argument("--no-env", action="store_true", help="disable environment overrides for an explicit file")
    parser.add_argument("--service", help="discover an existing service after startup")
    parser.add_argument("--namespace", default="default", help="discovery namespace; defaults to default")
    parser.add_argument("--timeout", type=positive_int, default=10000, help="overall discovery timeout in milliseconds")
    args = parser.parse_args()
    if args.default and args.no_env:
        parser.error("--no-env requires explicit file loading; omit --default")
    return args


def describe_context(context: SDKContext) -> dict:
    """Return effective configuration values without exposing the access token."""
    config = context.get_config()
    global_config = config.get_global()
    connector = global_config.get_server_connector()
    api = global_config.get_api()
    consumer = config.get_consumer()
    system = global_config.get_system()
    rule = consumer.get_circuit_breaker()
    return {
        "addresses": connector.get_addresses(),
        "protocol": connector.get_protocol(),
        "token_set": bool(connector.get_token()),
        "connect_timeout_ms": connector.get_connect_timeout(),
        "message_timeout_ms": connector.get_message_timeout(),
        "api_timeout_ms": api.get_timeout(),
        "bind_ip": api.get_bind_ip(),
        "max_retry_times": api.get_max_retry_times(),
        "cache_type": consumer.get_local_cache().get_type(),
        "service_refresh_interval_ms": consumer.get_local_cache().get_service_refresh_interval(),
        "loadbalancer": consumer.get_load_balancer().get_type(),
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
        "system_clusters": {
            name: {"namespace": cluster.get_namespace(), "service": cluster.get_service(),
                   "refresh_interval_ms": cluster.get_refresh_interval()}
            for name, cluster in (
                ("discoverCluster", system.get_discover_cluster()),
                ("healthCheckCluster", system.get_health_check_cluster()),
                ("monitorCluster", system.get_monitor_cluster()),
            )
        },
    }


def discover(consumer: ConsumerAPI, namespace: str, service: str, timeout: int) -> dict:
    """Discover instances within a bounded total timeout."""
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
    """Create shared APIs, report startup or discovery results, and destroy the context."""
    args = parse_args()
    try:
        if args.default:
            from polaris.pkg.config.loader import find_default_config_file

            config_file = find_default_config_file()
            config = (Configuration.from_file(str(config_file)) if config_file is not None
                      else Configuration.from_env())
            source = "default"
        else:
            path = (args.config or Path(__file__).with_name("polaris.yaml")).expanduser().resolve()
            config = Configuration.from_file(str(path), apply_env=not args.no_env)
            source = str(path)
        config.get_consumer().get_local_cache().persist_dir = str(
            demo_backup_directory(__file__, component="file")
        )
        context = init_context_by_config(
            config,
            log_options=demo_log_options(__file__, component="file"),
        )

        try:
            provider = ProviderAPI(context)
            consumer = ConsumerAPI(context)
            for api in (provider, consumer):
                api.check_available()
            result = describe_context(context)
            result["source"] = source
            result["shared_context"] = provider.context is consumer.context
            if args.service:
                result["discovery"] = discover(consumer, args.namespace, args.service, args.timeout)
        finally:
            context.destroy()

        result["context_destroyed"] = context.is_destroy()
        print(json.dumps(result, sort_keys=True))
        return 0
    except SDKError as exc:
        print(f"SDK error {exc.err_code}: {exc.msg}", file=sys.stderr)
    except TimeoutError:
        print(f"discovery timed out after {args.timeout} ms", file=sys.stderr)
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
