"""A ClawHub download is untrusted input, and unpacking it must stay bounded.

``ClawHubSource.fetch`` reads a downloaded zip straight into memory. Without
caps a small nested-deflate archive expands until the gateway dies, so these
tests pin the decompression ceilings (entry count, per-entry size, total size)
and the path rules that keep a bundle inside its own directory on every OS.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import AsyncIterator
from typing import Any

import pytest

from agentos.skills.hub import clawhub
from agentos.skills.hub.clawhub import ClawHubSource

_SKILL_MD = "---\nname: demo\ndescription: demo skill\n---\n# Demo\n"


class _StreamResponse:
    """Stands in for an httpx streaming response, counting chunks handed over."""

    def __init__(self, content: bytes, chunk_size: int = 4096) -> None:
        self._content = content
        self._chunk_size = chunk_size
        self.chunks_yielded = 0

    async def __aenter__(self) -> _StreamResponse:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        for start in range(0, max(len(self._content), 1), self._chunk_size):
            self.chunks_yielded += 1
            yield self._content[start : start + self._chunk_size]


def _client_returning(content: bytes, sink: list[_StreamResponse]) -> type:
    class _AsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _AsyncClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: Any) -> _StreamResponse:
            resp = _StreamResponse(content)
            sink.append(resp)
            return resp

    return _AsyncClient


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


async def _fetch(
    monkeypatch: pytest.MonkeyPatch, content: bytes, sink: list[_StreamResponse] | None = None
) -> Any:
    import httpx

    monkeypatch.setattr(
        httpx, "AsyncClient", _client_returning(content, sink if sink is not None else [])
    )
    return await ClawHubSource().fetch("demo")


@pytest.mark.asyncio
async def test_fetch_returns_an_ordinary_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    content = _zip({"demo/SKILL.md": _SKILL_MD.encode(), "demo/scripts/run.sh": b"echo hi\n"})

    bundle = await _fetch(monkeypatch, content)

    assert bundle is not None
    assert bundle.files["SKILL.md"] == _SKILL_MD
    assert bundle.files["scripts/run.sh"] == "echo hi\n"


@pytest.mark.asyncio
async def test_fetch_keeps_undecodable_non_skill_files_as_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _zip({"demo/SKILL.md": _SKILL_MD.encode(), "demo/logo.png": b"\x89PNG\xff\xfe"})

    bundle = await _fetch(monkeypatch, content)

    assert bundle is not None
    assert bundle.files["logo.png"] == b"\x89PNG\xff\xfe"


@pytest.mark.asyncio
async def test_fetch_rejects_a_skill_md_that_is_not_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    content = _zip({"demo/SKILL.md": b"\xff\xfe not utf-8"})

    assert await _fetch(monkeypatch, content) is None


@pytest.mark.asyncio
async def test_fetch_rejects_an_archive_that_expands_past_the_total_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The classic bomb: highly compressible zeros that dwarf the archive itself."""
    monkeypatch.setattr(clawhub, "_MAX_TOTAL_BYTES", 64 * 1024)
    monkeypatch.setattr(clawhub, "_MAX_ENTRY_BYTES", 64 * 1024)
    content = _zip({"demo/SKILL.md": _SKILL_MD.encode(), "demo/bomb.bin": b"\0" * (256 * 1024)})
    assert len(content) < 8 * 1024  # tiny on the wire, large in memory

    assert await _fetch(monkeypatch, content) is None


@pytest.mark.asyncio
async def test_fetch_rejects_an_entry_that_lies_about_its_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ZipInfo.file_size`` is attacker-controlled, so the running total decides."""
    monkeypatch.setattr(clawhub, "_MAX_ENTRY_BYTES", 32 * 1024)
    monkeypatch.setattr(clawhub, "_MAX_TOTAL_BYTES", 64 * 1024)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("demo/SKILL.md", _SKILL_MD)
        info = zipfile.ZipInfo("demo/bomb.bin")
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, b"\0" * (256 * 1024))
        # Understate the declared size so only the streaming cap can catch it.
        zf.filelist[-1].file_size = 1
    content = buf.getvalue()

    assert await _fetch(monkeypatch, content) is None


@pytest.mark.asyncio
async def test_fetch_rejects_an_archive_with_too_many_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(clawhub, "_MAX_ZIP_ENTRIES", 4)
    entries = {"demo/SKILL.md": _SKILL_MD.encode()}
    entries.update({f"demo/f{i}.txt": b"x" for i in range(10)})

    assert await _fetch(monkeypatch, _zip(entries)) is None


@pytest.mark.asyncio
async def test_fetch_stops_reading_an_oversized_download_mid_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The body is capped while it streams, so a decoded gzip bomb never lands in RAM."""
    monkeypatch.setattr(clawhub, "_MAX_ARCHIVE_BYTES", 4096)
    content = b"PK" + b"\0" * (64 * 4096)
    sink: list[_StreamResponse] = []

    assert await _fetch(monkeypatch, content, sink) is None
    # 4096-byte chunks against a 4096-byte cap: it gives up on the second one.
    assert sink[0].chunks_yielded == 2


@pytest.mark.asyncio
async def test_fetch_rejects_an_archive_flagged_encrypted_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """zipfile answers an encrypted entry with RuntimeError, not BadZipFile.

    Anything but a clean ``None`` escapes ``fetch`` and aborts the caller — a
    lockfile sync stops dead on the first poisoned archive.
    """
    content = bytearray(_zip({"demo/SKILL.md": _SKILL_MD.encode()}))
    # Set the "encrypted" general-purpose bit on every central-directory record.
    idx = content.find(b"PK\x01\x02")
    while idx != -1:
        content[idx + 8] |= 0x01
        idx = content.find(b"PK\x01\x02", idx + 4)

    assert await _fetch(monkeypatch, bytes(content)) is None


@pytest.mark.asyncio
async def test_fetch_still_accepts_a_raw_skill_md_body(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = await _fetch(monkeypatch, _SKILL_MD.encode())

    assert bundle is not None
    assert bundle.files["SKILL.md"] == _SKILL_MD


@pytest.mark.parametrize(
    "name",
    [
        "demo/../../etc/passwd",
        "demo/..\\..\\windows\\system32\\evil.dll",
        "demo/C:/Windows/evil.dll",
        "demo//etc/passwd",
        "..",
        "demo/",
    ],
)
def test_unsafe_zip_paths_are_refused(name: str) -> None:
    assert clawhub._safe_rel_path(name) is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("demo/SKILL.md", "SKILL.md"),
        ("demo/scripts/run.sh", "scripts/run.sh"),
        ("demo/./scripts/../SKILL.md", "SKILL.md"),
        ("SKILL.md", "SKILL.md"),
    ],
)
def test_ordinary_zip_paths_are_kept(name: str, expected: str) -> None:
    assert clawhub._safe_rel_path(name) == expected


@pytest.mark.asyncio
async def test_fetch_drops_a_traversing_entry_but_keeps_the_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _zip({"demo/SKILL.md": _SKILL_MD.encode(), "demo/../../evil.sh": b"rm -rf /"})

    bundle = await _fetch(monkeypatch, content)

    assert bundle is not None
    assert set(bundle.files) == {"SKILL.md"}
