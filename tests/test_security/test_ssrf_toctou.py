from __future__ import annotations

import socket
from typing import Any

import httpcore
import pytest

from agentos.tools import ssrf
from agentos.tools.types import SSRFBlockedError


class MockAsyncNetworkStream(httpcore.AsyncNetworkStream):
    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        pass

    async def aclose(self) -> None:
        pass

    async def start_tls(
        self,
        ssl_context: Any,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return self


class MockNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self.connected_hosts: list[str] = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        self.connected_hosts.append(host)
        return MockAsyncNetworkStream()


@pytest.mark.asyncio
async def test_validating_backend_pins_ip_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup mock DNS table
    dns_table = {
        "example.com": ["93.184.216.34"],
        "metadata.local": ["169.254.169.254"],
    }

    def mock_getaddrinfo(host: str, port: Any, *args: Any, **kwargs: Any) -> list[Any]:
        if host in dns_table:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (dns_table[host][0], port or 80))]
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    mock_backend = MockNetworkBackend()
    validating_backend = ssrf.ValidatingNetworkBackend(rule="fetch", backend=mock_backend)

    # 1. Test connecting to a safe host
    stream = await validating_backend.connect_tcp("example.com", 80)
    assert stream is not None
    # Verify that the underlying backend connected to the IP literal, NOT the hostname
    assert mock_backend.connected_hosts == ["93.184.216.34"]

    # 2. Test connecting to a blocked host (metadata IP)
    with pytest.raises(SSRFBlockedError) as exc_info:
        await validating_backend.connect_tcp("metadata.local", 80)
    assert "Blocked: metadata.local resolves to 169.254.169.254" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ssrf_guarded_client_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup mock DNS table where a hostname resolves to a safe IP
    dns_table = {
        "safe.com": ["93.184.216.34"],
    }

    def mock_getaddrinfo(host: str, port: Any, *args: Any, **kwargs: Any) -> list[Any]:
        if host in dns_table:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (dns_table[host][0], port or 80))]
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    # We build an ssrf_guarded_client with our mock backend
    mock_backend = MockNetworkBackend()

    # We construct a customized client by injecting our validating backend wrapper
    client = ssrf.ssrf_guarded_client(rule="fetch")

    # We swap the base backend on the validating backend to point to our mock_backend
    # Let's inspect the injected backend on the transport
    backend = client._transport._pool._network_backend
    assert isinstance(backend, ssrf.ValidatingNetworkBackend)
    backend._backend = mock_backend

    # Make request
    resp = await client.get("http://safe.com/get")
    # Our MockAsyncNetworkStream returned OK
    assert resp.status_code == 200
    assert mock_backend.connected_hosts == ["93.184.216.34"]
