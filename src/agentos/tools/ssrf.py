"""Shared SSRF protection for URL-fetching tools."""

from __future__ import annotations

import ipaddress
import socket
import typing
from collections.abc import Iterable
from typing import Any, Literal
from urllib.parse import urlparse

import httpcore
import httpx

from agentos.tools.types import SSRFBlockedError, UnsupportedURLSchemeError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

RFC2544_FAKE_IP_NETWORK = ipaddress.IPv4Network("198.18.0.0/15")

_HARD_BLOCKED_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

#: Hostnames that resolve to a cloud metadata service. Blocked by name as well
#: as by address, because a resolver that answers them at all is answering for
#: the credential endpoint.
_METADATA_HOSTNAMES: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)

#: Addresses that serve instance credentials to anything that can reach them.
#: These are the non-negotiable floor: unlike ordinary private ranges they have
#: no legitimate agent use, on any tool, under any configuration.
_METADATA_ADDRESSES: frozenset[IPAddress] = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),  # AWS / GCP / Azure / DO / Oracle
        ipaddress.ip_address("169.254.169.253"),  # Azure IMDS wire server
        ipaddress.ip_address("169.254.170.2"),  # AWS ECS task role credentials
        ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud
        ipaddress.ip_address("fd00:ec2::254"),  # AWS metadata over IPv6
    }
)

#: The whole link-local range. Nothing an agent should be talking to lives
#: here, and enumerating individual metadata addresses has repeatedly missed a
#: cloud vendor's variant.
_METADATA_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
)

_trusted_fake_ip_cidrs: tuple[IPNetwork, ...] = ()


def validate_trusted_fake_ip_cidrs(values: Iterable[str]) -> list[str]:
    """Return normalized fake-IP CIDRs or raise for unsafe entries."""
    networks: list[str] = []
    for raw in values:
        try:
            network = ipaddress.ip_network(str(raw).strip(), strict=False)
        except ValueError as exc:
            raise ValueError(f"trusted_fake_ip_cidrs entry {raw!r} is not a valid CIDR") from exc

        if not isinstance(network, ipaddress.IPv4Network) or not network.subnet_of(
            RFC2544_FAKE_IP_NETWORK
        ):
            raise ValueError(
                "trusted_fake_ip_cidrs may only contain subnets of "
                f"{RFC2544_FAKE_IP_NETWORK}; got {network}"
            )
        networks.append(str(network))
    return networks


def configure_trusted_fake_ip_cidrs(values: Iterable[str]) -> None:
    """Configure process-wide fake-IP CIDRs trusted by URL fetch guards."""
    global _trusted_fake_ip_cidrs
    normalized = validate_trusted_fake_ip_cidrs(values)
    _trusted_fake_ip_cidrs = tuple(ipaddress.ip_network(value) for value in normalized)


def get_trusted_fake_ip_cidrs() -> list[str]:
    """Return the process-wide trusted fake-IP CIDRs as normalized strings."""
    return [str(network) for network in _trusted_fake_ip_cidrs]


def _is_metadata_address(addr: IPAddress) -> bool:
    """Return whether *addr* is a cloud metadata endpoint."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        # ``::ffff:169.254.169.254`` is the same endpoint wearing a different
        # hat, and compares equal to neither the IPv4 address nor the IPv4
        # networks. Unwrap before deciding.
        addr = addr.ipv4_mapped
    if addr in _METADATA_ADDRESSES:
        return True
    return any(
        addr.version == network.version and addr in network for network in _METADATA_NETWORKS
    )


def assert_not_metadata_endpoint(url: str) -> None:
    """Raise :class:`SSRFBlockedError` if *url* targets a cloud metadata service.

    The security floor for tools that must keep reaching private addresses.
    ``http_request`` is routinely pointed at ``localhost`` and LAN services on
    purpose, so it cannot take the full :func:`validate_http_url_for_fetch`
    treatment — but no configuration makes the instance-credential endpoint a
    legitimate destination.

    A hostname that cannot be resolved is not blocked: the request that follows
    will fail on its own, and failing closed here would take the tool offline
    whenever DNS is unavailable.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        return
    if hostname in _METADATA_HOSTNAMES:
        raise SSRFBlockedError(
            f"Blocked request to {hostname}: cloud metadata endpoints serve instance "
            "credentials and are never a valid agent target."
        )

    try:
        literal = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if _is_metadata_address(literal):
            raise SSRFBlockedError(
                f"Blocked request to {hostname}: link-local/metadata addresses serve "
                "instance credentials and are never a valid agent target."
            )
        return

    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError, ValueError):
        return
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:  # pragma: no cover - getaddrinfo returned a non-address
            continue
        if _is_metadata_address(addr):
            raise SSRFBlockedError(
                f"Blocked request to {hostname}: it resolves to {addr}, a cloud "
                "metadata endpoint that serves instance credentials."
            )


def validate_http_url_for_fetch(
    url: str,
    *,
    trusted_fake_ip_cidrs: Iterable[str] | None = None,
) -> None:
    """Validate that an HTTP(S) URL does not resolve to a blocked address."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsupportedURLSchemeError("Only HTTP/HTTPS URLs are supported")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: no hostname")

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve hostname: {hostname}") from exc

    trusted_networks = (
        tuple(
            ipaddress.ip_network(value)
            for value in validate_trusted_fake_ip_cidrs(trusted_fake_ip_cidrs)
        )
        if trusted_fake_ip_cidrs is not None
        else _trusted_fake_ip_cidrs
    )

    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        block_reason = _hard_block_reason(addr)
        if block_reason is not None:
            raise SSRFBlockedError(_blocked_message(hostname, addr, block_reason))
        if _is_trusted_fake_ip(addr, trusted_networks):
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            reason = (
                f"reserved/private range; configure [tools].trusted_fake_ip_cidrs "
                f"with {RFC2544_FAKE_IP_NETWORK} only if this is fake-IP DNS"
                if addr in RFC2544_FAKE_IP_NETWORK
                else "private/internal range"
            )
            raise SSRFBlockedError(_blocked_message(hostname, addr, reason))


def _hard_block_reason(addr: IPAddress) -> str | None:
    for network in _HARD_BLOCKED_NETWORKS:
        if addr.version == network.version and addr in network:
            return f"hard-blocked network {network}"
    return None


def _is_trusted_fake_ip(addr: IPAddress, trusted_networks: tuple[IPNetwork, ...]) -> bool:
    return any(addr.version == network.version and addr in network for network in trusted_networks)


def _blocked_message(hostname: str, addr: IPAddress, reason: str) -> str:
    return f"Blocked: {hostname} resolves to {addr} ({reason})"


class ValidatingNetworkBackend(httpcore.AsyncNetworkBackend):
    """Network backend that resolves and validates hostnames before connecting.

    Presents a DNS-rebinding TOCTOU defense by pinning the validated IP address
    and connecting directly to it while preserving the original host for TLS
    handshake (SNI and certificate validation).
    """

    def __init__(
        self,
        rule: Literal["fetch", "metadata"] = "fetch",
        backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._rule = rule
        self._backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: typing.Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        clean_host = host.strip().lower().rstrip(".")
        if clean_host in _METADATA_HOSTNAMES:
            raise SSRFBlockedError(
                f"Blocked request to {host}: cloud metadata endpoints serve instance "
                "credentials and are never a valid agent target."
            )

        try:
            infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except (socket.gaierror, UnicodeError, ValueError) as exc:
            raise httpcore.ConnectError(f"Cannot resolve hostname: {host}") from exc

        if not infos:
            raise httpcore.ConnectError(f"No IP addresses found for hostname: {host}")

        ips: list[str] = []
        for info in infos:
            try:
                ip = info[4][0]
                if isinstance(ip, str):
                    ips.append(ip)
            except IndexError:
                continue

        for ip in ips:
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue

            if self._rule == "metadata":
                if _is_metadata_address(addr):
                    raise SSRFBlockedError(
                        f"Blocked request to {host}: link-local/metadata addresses serve "
                        "instance credentials and are never a valid agent target."
                    )
            else:
                block_reason = _hard_block_reason(addr)
                if block_reason is not None:
                    raise SSRFBlockedError(_blocked_message(host, addr, block_reason))
                if _is_trusted_fake_ip(addr, _trusted_fake_ip_cidrs):
                    continue
                if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                    reason = (
                        f"reserved/private range; configure [tools].trusted_fake_ip_cidrs "
                        f"with {RFC2544_FAKE_IP_NETWORK} only if this is fake-IP DNS"
                        if addr in RFC2544_FAKE_IP_NETWORK
                        else "private/internal range"
                    )
                    raise SSRFBlockedError(_blocked_message(host, addr, reason))

        # Target the first resolved and validated IP literal
        target_ip = ips[0]
        return await self._backend.connect_tcp(
            host=target_ip,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: typing.Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._backend.connect_unix_socket(
            path=path,
            timeout=timeout,
            socket_options=socket_options,
        )

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


def ssrf_guarded_client(
    *,
    rule: Literal["fetch", "metadata"] = "fetch",
    **kwargs: Any,
) -> httpx.AsyncClient:
    """Build a normal AsyncClient and swap in the ValidatingNetworkBackend."""
    client = httpx.AsyncClient(**kwargs)
    backend = ValidatingNetworkBackend(rule=rule)

    def _inject(transport: Any) -> None:
        if isinstance(transport, httpx.AsyncHTTPTransport):
            if hasattr(transport, "_pool") and hasattr(transport._pool, "_network_backend"):
                transport._pool._network_backend = backend

    if hasattr(client, "_transport") and client._transport is not None:
        _inject(client._transport)
    if hasattr(client, "_mounts") and isinstance(client._mounts, dict):
        for transport in client._mounts.values():
            _inject(transport)

    return client
