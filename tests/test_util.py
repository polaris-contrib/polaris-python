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

"""SDK address resolution with only interface enumeration and TCP I/O replaced."""

import asyncio
import socket
from types import SimpleNamespace

import pytest

from polaris.pkg.model import util


class FakeWriter:
    """Track closure of a probed connection with a configurable local address."""

    def __init__(self, address):
        self.address = address
        self.closed = False
        self.waited_closed = False

    def get_extra_info(self, name):
        assert name == "sockname"
        return self.address

    def close(self):
        self.closed = True

    async def wait_closed(self):
        self.waited_closed = True


@pytest.mark.parametrize("family,address,expected", [
    (socket.AF_INET, "192.0.2.1", "192.0.2.1"),
    (socket.AF_INET6, "2001:db8::1", "2001:db8::1"),
    (socket.AF_INET6, "fe80::1%test0", "fe80::1"),
])
def test_get_ip_selects_only_named_interface(monkeypatch, family, address, expected):
    monkeypatch.setattr(util.psutil, "net_if_addrs", lambda: {
        "other": [SimpleNamespace(family=socket.AF_INET, address="192.0.2.2")],
        "test0": [SimpleNamespace(family=-1, address="mac"),
                  SimpleNamespace(family=family, address=address)],
    })
    assert util.get_ip("test0") == expected


@pytest.mark.parametrize("interfaces", [
    {}, {"other": [SimpleNamespace(family=socket.AF_INET, address="192.0.2.2")]},
    {"test0": []}, {"test0": [SimpleNamespace(family=-1, address="mac")]},
])
def test_get_ip_rejects_missing_interface_or_address(monkeypatch, interfaces):
    monkeypatch.setattr(util.psutil, "net_if_addrs", lambda: interfaces)
    with pytest.raises(OSError, match="test0"):
        util.get_ip("test0")


@pytest.mark.parametrize("endpoint,local_address,host,expected", [
    ("registry.example:8091", ("192.0.2.1", 1234), "registry.example", "192.0.2.1"),
    ("[2001:db8::2]:8091", ("2001:db8::1", 1234, 0, 0), "2001:db8::2", "2001:db8::1"),
])
@pytest.mark.asyncio
async def test_get_local_ip_probes_configured_endpoint_and_closes_connection(
    monkeypatch, endpoint, local_address, host, expected,
):
    writer = FakeWriter(local_address)
    calls = []

    async def connect(server, port):
        calls.append((server, port))
        return None, writer

    monkeypatch.setattr(util.asyncio, "open_connection", connect)
    assert await util.get_local_ip(endpoint, 500) == expected
    assert calls == [(host, 8091)]
    assert writer.closed and writer.waited_closed


@pytest.mark.asyncio
async def test_get_local_ip_timeout_cancels_connection_attempt(monkeypatch):
    cancelled = asyncio.Event()

    async def connect(host, port):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(util.asyncio, "open_connection", connect)
    with pytest.raises(TimeoutError):
        await util.get_local_ip("registry:8091", 10)
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_get_local_ip_closes_connection_with_no_local_address(monkeypatch):
    writer = FakeWriter(None)

    async def connect(host, port):
        return None, writer

    monkeypatch.setattr(util.asyncio, "open_connection", connect)
    with pytest.raises(OSError, match="no local IP"):
        await util.get_local_ip("registry:8091", 500)
    assert writer.closed and writer.waited_closed


@pytest.mark.asyncio
async def test_get_local_ip_close_timeout_still_closes_socket(monkeypatch):
    writer = FakeWriter(("192.0.2.1", 1234))

    async def wait_closed():
        await asyncio.Event().wait()

    async def connect(host, port):
        return None, writer

    writer.wait_closed = wait_closed
    monkeypatch.setattr(util.asyncio, "open_connection", connect)
    with pytest.raises(TimeoutError):
        await util.get_local_ip("registry:8091", 10)
    assert writer.closed


@pytest.mark.asyncio
async def test_get_local_ip_reads_real_tcp_source_and_server_observes_close():
    disconnected = asyncio.Event()

    async def accept(reader, writer):
        try:
            assert await reader.read() == b""
        finally:
            writer.close()
            await writer.wait_closed()
            disconnected.set()

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        assert await util.get_local_ip(f"127.0.0.1:{port}", 500) == "127.0.0.1"
        await asyncio.wait_for(disconnected.wait(), 1)
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_get_local_ip_closes_connection_on_cancellation(monkeypatch):
    writer = FakeWriter(("192.0.2.1", 1234))
    closing = asyncio.Event()

    async def wait_closed():
        closing.set()
        await asyncio.Event().wait()

    async def connect(host, port):
        return None, writer

    writer.wait_closed = wait_closed
    monkeypatch.setattr(util.asyncio, "open_connection", connect)
    task = asyncio.create_task(util.get_local_ip("registry:8091", 500))
    await closing.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert writer.closed


@pytest.mark.parametrize("endpoint", ["missing-port", ":8091", "registry:0", "registry:65536", "registry:abc"])
@pytest.mark.asyncio
async def test_get_local_ip_rejects_invalid_endpoint_before_connect(monkeypatch, endpoint):
    async def connect(host, port):
        raise AssertionError("invalid endpoint must not connect")

    monkeypatch.setattr(util.asyncio, "open_connection", connect)
    with pytest.raises(ValueError):
        await util.get_local_ip(endpoint, 500)
