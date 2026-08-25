"""The ``download`` install kind writes a file and marks it executable.

Every value it works from — the URL and the destination name — comes out of
skill frontmatter, and a hub skill is third-party content. These tests pin the
two properties that keeps safe: the name can only ever land inside
``~/.local/bin``, and neither the declared URL nor any redirect it follows may
reach a private address.
"""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from agentos.skills.hub import deps
from agentos.skills.install_kinds import InstallSpecError
from agentos.skills.types import SkillInstallSpec


def _spec(
    *, url: str = "https://example.test/bin", bins: list[str] | None = None
) -> SkillInstallSpec:
    return SkillInstallSpec(
        kind="download", id="bin", url=url, bins=bins if bins is not None else ["bin"]
    )


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


# --------------------------------------------------------------------------
# Destination resolution
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../../../.zshrc",
        "../../.profile",
        "/etc/cron.d/pwn",
        ".bashrc",
        "-rf",
        "sub/dir",
        "",
    ],
)
def test_resolve_download_dest_refuses_names_that_leave_the_bin_dir(
    fake_home: Path, name: str
) -> None:
    with pytest.raises(InstallSpecError):
        deps._resolve_download_dest(_spec(bins=[name]), "https://example.test/bin")


def test_resolve_download_dest_accepts_a_plain_binary_name(fake_home: Path) -> None:
    dest = deps._resolve_download_dest(_spec(bins=["ripgrep"]), "https://example.test/bin")
    assert dest == fake_home / ".local" / "bin" / "ripgrep"


def test_resolve_download_dest_refuses_to_write_through_a_symlink(fake_home: Path) -> None:
    outside = fake_home / "secret.txt"
    outside.write_text("original", encoding="utf-8")
    link = fake_home / ".local" / "bin" / "tool"
    link.symlink_to(outside)

    with pytest.raises(InstallSpecError, match="symlink"):
        deps._resolve_download_dest(_spec(bins=["tool"]), "https://example.test/bin")
    assert outside.read_text(encoding="utf-8") == "original"


def test_install_download_refuses_a_traversal_name_without_fetching(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _must_not_fetch(url: str, dest: Path) -> None:
        raise AssertionError("fetch must not be attempted for a rejected name")

    monkeypatch.setattr(deps, "_fetch_to_file", _must_not_fetch)
    result = asyncio.run(deps.install_download(_spec(bins=["../../../.zshrc"])))

    assert result.success is False
    assert not (fake_home / ".zshrc").exists()


# --------------------------------------------------------------------------
# Fetch: redirects and size
# --------------------------------------------------------------------------


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        url: str,
        headers: dict[str, str] | None = None,
        chunks: tuple[bytes, ...] = (),
    ) -> None:
        self.status_code = status_code
        self.url = url
        self.headers = headers or {}
        self._chunks = chunks
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise ValueError(f"HTTP {self.status_code}")

    async def aiter_bytes(self) -> Any:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse], **_kwargs: Any) -> None:
        self._responses = responses
        self.requested: list[str] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    def build_request(self, method: str, url: str) -> str:
        return url

    async def send(self, request: str, stream: bool = False) -> _FakeResponse:
        self.requested.append(request)
        return self._responses.pop(0)


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch, responses: list[_FakeResponse]
) -> dict[str, _FakeClient]:
    import httpx

    holder: dict[str, _FakeClient] = {}

    def _factory(**kwargs: Any) -> _FakeClient:
        client = _FakeClient(responses, **kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    return holder


#: Hostnames the fake resolver knows. Resolution is the only part of the SSRF
#: guard that needs the network, so stubbing it lets the real rules run offline.
_FAKE_DNS = {
    "example.test": "93.184.216.34",  # TEST-NET-ish public address
    "cdn.example.test": "93.184.216.35",
    "internal.example.test": "10.0.0.7",  # RFC 1918
}


def _fake_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve a fixed table instead of querying DNS.

    The real :func:`validate_http_url_for_fetch` still runs — only the lookup is
    replaced — so these tests exercise the shipped guard rather than a stand-in.
    """
    import agentos.tools.ssrf as ssrf_mod

    def _getaddrinfo(host: str, _port: object, *_args: Any, **_kwargs: Any) -> list[Any]:
        try:
            addr = _FAKE_DNS[host]
        except KeyError:
            import socket as _socket

            raise _socket.gaierror(f"unknown host in test table: {host}") from None
        return [(None, None, None, None, (addr, 0))]

    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", _getaddrinfo)


def test_redirect_to_a_private_address_is_blocked(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_dns(monkeypatch)
    responses = [
        _FakeResponse(
            status_code=302,
            url="https://example.test/bin",
            headers={"location": "https://internal.example.test/payload"},
        )
    ]
    _install_fake_client(monkeypatch, responses)

    from agentos.tools.ssrf import SSRFBlockedError

    dest = fake_home / ".local" / "bin" / "bin"
    # Specifically the SSRF guard, not merely "something raised": the point is
    # that the hop is validated, and a bare Exception assertion would also pass
    # against a build where the fetch helper does not exist at all.
    with pytest.raises(SSRFBlockedError):
        asyncio.run(deps._fetch_to_file("https://example.test/bin", dest))
    assert not dest.exists()


def test_install_download_reports_a_blocked_redirect_as_failure(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_dns(monkeypatch)
    responses = [
        _FakeResponse(
            status_code=302,
            url="https://example.test/bin",
            headers={"location": "https://internal.example.test/payload"},
        )
    ]
    holder = _install_fake_client(monkeypatch, responses)

    result = asyncio.run(deps.install_download(_spec()))
    assert result.success is False
    # The redirect must actually have been attempted and refused, rather than
    # the call failing earlier for an unrelated reason.
    assert holder["client"].requested == ["https://example.test/bin"]
    assert "internal.example.test" in result.message
    assert not (fake_home / ".local" / "bin" / "bin").exists()


def test_download_over_the_size_cap_leaves_nothing_behind(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_dns(monkeypatch)
    monkeypatch.setattr(deps, "_MAX_DOWNLOAD_BYTES", 8)
    responses = [
        _FakeResponse(
            status_code=200,
            url="https://example.test/bin",
            chunks=(b"aaaaaaaa", b"bbbbbbbb"),
        )
    ]
    _install_fake_client(monkeypatch, responses)

    dest = fake_home / ".local" / "bin" / "bin"
    with pytest.raises(ValueError, match="cap"):
        asyncio.run(deps._fetch_to_file("https://example.test/bin", dest))

    assert not dest.exists()
    assert list((fake_home / ".local" / "bin").iterdir()) == []


def test_successful_download_is_executable_and_atomic(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_dns(monkeypatch)
    responses = [
        _FakeResponse(
            status_code=200, url="https://example.test/bin", chunks=(b"#!/bin/sh\n", b"echo hi\n")
        )
    ]
    _install_fake_client(monkeypatch, responses)

    dest = fake_home / ".local" / "bin" / "bin"
    asyncio.run(deps._fetch_to_file("https://example.test/bin", dest))

    assert dest.read_bytes() == b"#!/bin/sh\necho hi\n"
    mode = stat.S_IMODE(dest.stat().st_mode)
    if os.name == "nt":
        # Windows has no execute bit; chmod only drives the read-only flag, and
        # what makes a file runnable there is PATHEXT. Assert the part that is
        # real on this platform: the file is writable, not left read-only.
        assert mode & stat.S_IWUSR
    else:
        assert mode & stat.S_IXUSR
    # no .part leftovers
    assert [p.name for p in (fake_home / ".local" / "bin").iterdir()] == ["bin"]


def test_redirect_chain_is_bounded(fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_dns(monkeypatch)
    responses = [
        _FakeResponse(
            status_code=302,
            url=f"https://example.test/hop{i}",
            headers={"location": f"https://example.test/hop{i + 1}"},
        )
        for i in range(deps._MAX_DOWNLOAD_REDIRECTS + 2)
    ]
    _install_fake_client(monkeypatch, responses)

    dest = fake_home / ".local" / "bin" / "bin"
    with pytest.raises(ValueError, match="redirect"):
        asyncio.run(deps._fetch_to_file("https://example.test/hop0", dest))
    assert not dest.exists()


def test_url_basename_fallback_is_validated_too(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A spec with no ``bins`` falls back to the URL's last segment."""

    async def _must_not_fetch(url: str, dest: Path) -> None:
        raise AssertionError("fetch must not be attempted for a rejected name")

    monkeypatch.setattr(deps, "_fetch_to_file", _must_not_fetch)
    result = asyncio.run(deps.install_download(_spec(url="https://example.test/.zshrc", bins=[])))
    assert result.success is False


def test_os_replace_is_used_so_no_partial_file_is_ever_executable(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_dns(monkeypatch)
    seen: list[str] = []
    real_replace = os.replace

    def _spy(src: Any, dst: Any) -> None:
        seen.append(str(dst))
        real_replace(src, dst)

    monkeypatch.setattr(deps.os, "replace", _spy)
    responses = [_FakeResponse(status_code=200, url="https://example.test/bin", chunks=(b"x",))]
    _install_fake_client(monkeypatch, responses)

    dest = fake_home / ".local" / "bin" / "bin"
    asyncio.run(deps._fetch_to_file("https://example.test/bin", dest))
    assert seen == [str(dest)]
