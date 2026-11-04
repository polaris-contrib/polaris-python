#!/usr/bin/python
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
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Select instances through the Java-aligned before/core/after router chains."""

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2])]
from examples._internal._runtime import configure_e2e_event_reporting, demo_backup_directory, demo_log_options

import argparse
import asyncio
import math
import os

from polaris.api.consumer import ConsumerAPI, create_consumer_by_config
from polaris.api.log import LogLevel
from polaris.pkg.config.api import Configuration
from polaris.pkg.model.error import SDKError
from polaris.pkg.model.service import GetOneInstanceRequest, RetStatus, ServiceCallResult

CONSUMER_INSTANCE = None


def parse_metadata(items):
    metadata = {}
    for item in items:
        if "=" not in item:
            raise ValueError("metadata must use key=value format")
        key, value = item.split("=", 1)
        if not key or not value:
            raise ValueError("metadata key and value cannot be empty")
        metadata[key] = value
    return metadata


def get_api(mode, failover):
    global CONSUMER_INSTANCE
    if CONSUMER_INSTANCE is None:
        config = Configuration()
        config.set_default()
        configure_e2e_event_reporting(config)
        connector = config.get_global().get_server_connector()
        connector.addresses = [os.getenv("POLARIS_SERVER", "127.0.0.1:8091")]
        connector.token = os.getenv("POLARIS_TOKEN", "")
        connector.connect_timeout = 2 * 1000
        config.get_global().get_admin().port = 0
        router = config.get_consumer().get_service_router()
        if mode == "metadata":
            router.chain = ["metadataRouter"]
            router.plugin["metadataRouter"] = {"metadataFailOverType": failover}
        config.get_consumer().get_local_cache().persist_dir = str(
            demo_backup_directory(__file__, component=mode))
        CONSUMER_INSTANCE = create_consumer_by_config(
            config,
            log_options=demo_log_options(__file__, level=LogLevel.Warn, component=mode),
        )
    return CONSUMER_INSTANCE


def make_request(namespace, service, metadata, failover):
    return GetOneInstanceRequest(
        namespace=namespace,
        service=service,
        use_discover_cache=True,
        metadata=metadata,
        metadata_failover_type=failover if metadata else None,
    )


async def get_one_instance(consumer, namespace, service, metadata, failover):
    try:
        instance = await consumer.async_get_one_instance(
            make_request(namespace, service, metadata, failover))
    except SDKError as exc:
        raise RuntimeError(f"Polaris SDK error: {exc!r}") from exc
    if instance is None:
        raise RuntimeError("no available node")
    print(f"host:{instance.get_host()} port:{instance.get_port()}")
    await consumer.async_update_service_call_result(ServiceCallResult(
        called_instance=instance,
        ret_status=RetStatus.RetSuccess,
        ret_code=0,
        delay=1,
    ))


def sync_get_one_instance(consumer, namespace, service, metadata, failover):
    instance = consumer.get_one_instance(make_request(namespace, service, metadata, failover))
    if instance is None:
        raise RuntimeError("no available node")
    print(f"host:{instance.get_host()} port:{instance.get_port()}")
    consumer.sync_update_service_call_result(ServiceCallResult(
        called_instance=instance,
        ret_status=RetStatus.RetSuccess,
        ret_code=0,
        delay=1,
    ))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Select instances through the configured service router chain")
    parser.add_argument("namespace")
    parser.add_argument("service")
    parser.add_argument("times", type=int)
    parser.add_argument("--mode", choices=("default", "metadata"), default="default")
    parser.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--failover", choices=("none", "all", "others"), default="all")
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args(argv)
    if args.times <= 0 or not math.isfinite(args.interval) or args.interval < 0:
        parser.error("times must be positive and interval must be finite and nonnegative")
    try:
        metadata = parse_metadata(args.metadata)
    except ValueError as exc:
        parser.error(str(exc))

    consumer = get_api(args.mode, args.failover)
    try:
        async def run_async():
            for _ in range(args.times):
                await get_one_instance(consumer, args.namespace, args.service, metadata, args.failover)
                await asyncio.sleep(args.interval)

        asyncio.run(run_async())
        print("use sync method")
        for _ in range(args.times):
            sync_get_one_instance(consumer, args.namespace, args.service, metadata, args.failover)
    finally:
        consumer.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
