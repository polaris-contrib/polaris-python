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

import asyncio
import ipaddress
import socket
from contextlib import suppress

import psutil


def get_ip(ifname: str) -> str:
    """Return an IP from the named interface without falling back to another one."""
    for address in psutil.net_if_addrs().get(ifname, ()):
        if address.family in (socket.AF_INET, socket.AF_INET6):
            return str(ipaddress.ip_address(address.address.split("%", 1)[0]))
    raise OSError(f"no IP address found for interface {ifname}")


async def get_local_ip(address: str, timeout: int) -> str:
    """Probe the TCP source IP for a configured server within a millisecond timeout."""
    host, port = get_ip_from_int_with_port(address)
    if not host or not 0 < port < 65536:
        raise ValueError(f"invalid server address {address}")
    async with asyncio.timeout(timeout / 1000):
        _, writer = await asyncio.open_connection(host, port)
        try:
            local_address = writer.get_extra_info("sockname")
            if not local_address or not local_address[0]:
                raise OSError("TCP connection has no local IP address")
            return str(ipaddress.ip_address(local_address[0]))
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()


def get_ip_from_int_with_port(ipstr):
    host, port = ipstr.rsplit(":", 1)
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        host = str(ipaddress.IPv4Address(int(host)))
    except ValueError:
        pass
    return host, int(port)
