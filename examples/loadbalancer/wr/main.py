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
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

# -*- coding: utf-8 -*-

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parents[3])]
from examples._internal._runtime import demo_backup_directory, demo_log_options

import argparse
import asyncio
import math
import os

from polaris.api.consumer import ConsumerAPI
from polaris.api.consumer import create_consumer_by_config
from polaris.api.log import LogLevel
from polaris.pkg.config.api import Configuration
from polaris.pkg.model.error import SDKError
from polaris.pkg.model.service import GetOneInstanceRequest
from polaris.pkg.model.service import RetStatus
from polaris.pkg.model.service import ServiceCallResult

CONSUMER_INSTANCE = None


def get_api():
    global CONSUMER_INSTANCE
    if not CONSUMER_INSTANCE:
        config = Configuration()
        config.set_default()
        connector = config.get_global().get_server_connector()
        connector.addresses = [os.getenv("POLARIS_SERVER", "127.0.0.1:8091")]
        connector.token = os.getenv("POLARIS_TOKEN", "")
        config.get_global().get_server_connector().connect_timeout = 2 * 1000
        config.get_global().get_admin().port = 0
        config.get_consumer().get_local_cache().persist_dir = str(
            demo_backup_directory(__file__, component="wr")
        )
        CONSUMER_INSTANCE = create_consumer_by_config(
            config,
            log_options=demo_log_options(__file__, level=LogLevel.Warn, component="wr"),
        )
    return CONSUMER_INSTANCE


async def get_one_instance(consumer_client: ConsumerAPI, namespace: str, server_name: str):
    request = GetOneInstanceRequest(namespace=namespace, service=server_name, use_discover_cache=True)
    # 获取一个实例
    try:
        ret = await consumer_client.async_get_one_instance(request)
    except SDKError as exc:
        raise RuntimeError(f"Polaris SDK error: {exc!r}") from exc

    if not ret:
        raise Exception("no available node")

    print('host:{host} port:{port}'.format(host=ret.get_host(), port=ret.get_port()))

    # 上报熔断数据, 包括调用后端时候成功，这段上报逻辑需要放在实际调用下游之后
    report_req = ServiceCallResult(
        called_instance=ret, ret_status=RetStatus.RetSuccess, ret_code=0, delay=1,
    )
    await consumer_client.async_update_service_call_result(report_req)

def sync_get_one_instance(consumer_client: ConsumerAPI, namespace: str, server_name: str):
    request = GetOneInstanceRequest(namespace=namespace, service=server_name, use_discover_cache=True)
    # 获取一个实例
    ret = consumer_client.get_one_instance(request)
    if not ret:
        raise Exception("no available node")
    print('host:{host} port:{port}'.format(host=ret.get_host(), port=ret.get_port()))

    # 上报熔断数据, 包括调用后端时候成功，这段上报逻辑需要放在实际调用下游之后
    report_req = ServiceCallResult(
        called_instance=ret, ret_status=RetStatus.RetSuccess, ret_code=0, delay=1,
    )

    consumer_client.sync_update_service_call_result(report_req)

def main(argv=None):
    parser = argparse.ArgumentParser(description="Select instances using weighted random load balancing")
    parser.add_argument("namespace")
    parser.add_argument("service")
    parser.add_argument("times", type=int)
    parser.add_argument("--interval", type=float, default=5, help="seconds between asynchronous selections")
    args = parser.parse_args(argv)
    if args.times <= 0 or not math.isfinite(args.interval) or args.interval < 0:
        parser.error("times must be positive and interval must be finite and nonnegative")
    namespace, service, times = args.namespace, args.service, args.times
    # IMPORTANT: consumer对象维护了数据缓存，需要全局复用
    consumer = get_api()
    try:
        async def run():
            for _ in range(times):
                await get_one_instance(consumer, namespace, service)
                await asyncio.sleep(args.interval)

        asyncio.run(run())
        print("use sync method")
        for _ in range(times):
            sync_get_one_instance(consumer, namespace, service)
    finally:
        consumer.destroy()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
