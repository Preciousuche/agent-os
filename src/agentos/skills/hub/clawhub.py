"""ClawHub Community source adapter - connects to clawhub.ai API."""

from __future__ import annotations

import ntpath
import posixpath
from typing import TYPE_CHECKING

import structlog

from agentos.env import trust_env as _trust_env
from agentos.skills.hub.source import SkillBundle, SkillMeta, SkillSource

if TYPE_CHECKING:  # pragma: no cover - import kept lazy at runtime
    import zipfile

log = structlog.get_logger(__name__)

_DEFAULT_BASE_URL = "https://clawhub.ai"

# Decompression caps for a downloaded skill archive. A skill bundle is a handful
# of text files plus the odd asset, so these ceilings sit far above any real
# skill and far below what it takes to OOM the gateway. Without them a few tens
# of KB of nested deflate (a zip bomb) expands into memory unbounded.
_MAX_ARCHIVE_BYTES = 16 * 1024 * 1024  # compressed bytes accepted off the wire
_MAX_ZIP_ENTRIES = 2_000
_MAX_ENTRY_BYTES = 8 * 1024 * 1024  # uncompressed, per entry
_MAX_TOTAL_BYTES = 32 * 1024 * 1024  # uncompressed, whole archive
_ZIP_READ_CHUNK = 64 * 1024


def _safe_rel_path(name: str) -> str | None:
    """Strip a zip entry's wrapper directory, or return ``None`` to skip it.

    The archive names come from a community registry, so they are untrusted.
    ``posixpath.normpath`` alone does not neutralize Windows-style escapes
    (``..\\``, ``C:\\``) — those are rejected outright rather than normalized.
    """
    rel = name.split("/", 1)[1] if "/" in name else name
    if not rel or "\\" in rel or ntpath.splitdrive(rel)[0]:
        return None
    rel = posixpath.normpath(rel)
    if rel in (".", "..") or rel.startswith(("../", "/")):
        return None
    return rel


def _read_capped(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes | None:
    """Decompress one entry, returning ``None`` once it exceeds ``limit`` bytes.

    ``ZipInfo.file_size`` is attacker-controlled metadata, so the declared sizes
    checked by the caller are only a first filter; this running total is what
    actually stops an archive that lies about how much it expands to.
    """
    chunks: list[bytes] = []
    total = 0
    with zf.open(info) as fh:
        while True:
            chunk = fh.read(_ZIP_READ_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                return None
            chunks.append(chunk)
    return b"".join(chunks)


class ClawHubSource(SkillSource):
    """Skill source backed by the ClawHub community registry."""

    def __init__(self, base_url: str = _DEFAULT_BASE_URL, token: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token

    @property
    def source_id(self) -> str:
        return "clawhub"

    @property
    def trust_level(self) -> str:
        return "community"

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def search(self, query: str, limit: int = 20) -> list[SkillMeta]:
        import httpx

        url = f"{self._base_url}/api/v1/search"
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=_trust_env()) as client:
                resp = await client.get(
                    url, params={"q": query, "limit": limit}, headers=self._headers()
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            log.warning("clawhub.search_failed", error=str(exc))
            return []

        # Handle rate limit / error disguised as 200
        if isinstance(data, str) or (isinstance(data, dict) and "error" in data):
            log.warning("clawhub.search_error", data=str(data)[:100])
            return []

        results = []
        for item in data if isinstance(data, list) else data.get("results", data.get("skills", [])):
            results.append(
                SkillMeta(
                    name=item.get("displayName", item.get("name", item.get("slug", ""))),
                    # `or ""` (not a .get default): the API may send an explicit
                    # null, which .get returns as None and would break the str
                    # contract downstream (e.g. CLI description slicing).
                    description=item.get("summary") or item.get("description") or "",
                    version=item.get("version", ""),
                    author=item.get("author", ""),
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    identifier=item.get("slug", item.get("name", "")),
                    homepage=item.get("homepage", ""),
                    license=item.get("license", ""),
                    tags=item.get("tags", []),
                )
            )
        return results[:limit]

    async def fetch(self, identifier: str) -> SkillBundle | None:
        import io
        import zipfile
        import zlib

        import httpx

        url = f"{self._base_url}/api/v1/download"
        try:
            async with httpx.AsyncClient(timeout=30, trust_env=_trust_env()) as client:
                # Streamed, not buffered: httpx transparently gunzips a
                # Content-Encoding body with no ceiling of its own, so a small
                # gzipped response could otherwise fill memory before a single
                # zip cap below gets a say.
                async with client.stream(
                    "GET", url, params={"slug": identifier}, headers=self._headers()
                ) as resp:
                    resp.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > _MAX_ARCHIVE_BYTES:
                            log.warning(
                                "clawhub.fetch_archive_too_large",
                                identifier=identifier,
                                limit=_MAX_ARCHIVE_BYTES,
                            )
                            return None
                        chunks.append(chunk)
                    content = b"".join(chunks)
        except Exception as exc:
            log.warning("clawhub.fetch_failed", identifier=identifier, error=str(exc))
            return None

        text_body = content.decode("utf-8", errors="replace")

        # Detect error responses disguised as 200 (e.g. rate limiting)
        if len(content) < 50 and not content.startswith(b"PK") and not content.startswith(b"---"):
            text = text_body.strip()
            if (
                "rate limit" in text.lower()
                or "error" in text.lower()
                or "not found" in text.lower()
            ):
                log.warning("clawhub.fetch_error_response", identifier=identifier, body=text[:100])
                return None

        files: dict[str, str | bytes] = {}
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                infos = zf.infolist()
                if len(infos) > _MAX_ZIP_ENTRIES:
                    log.warning(
                        "clawhub.fetch_zip_too_many_entries",
                        identifier=identifier,
                        entries=len(infos),
                        limit=_MAX_ZIP_ENTRIES,
                    )
                    return None
                if sum(info.file_size for info in infos) > _MAX_TOTAL_BYTES:
                    log.warning(
                        "clawhub.fetch_zip_declared_size_too_large",
                        identifier=identifier,
                        limit=_MAX_TOTAL_BYTES,
                    )
                    return None

                budget = _MAX_TOTAL_BYTES
                for info in infos:
                    name = info.filename
                    if info.is_dir() or name.endswith("/"):
                        continue
                    rel = _safe_rel_path(name)
                    if rel is None:
                        log.warning("clawhub.fetch_zip_unsafe_path", identifier=identifier)
                        continue
                    if info.file_size > _MAX_ENTRY_BYTES:
                        log.warning(
                            "clawhub.fetch_zip_entry_too_large",
                            identifier=identifier,
                            entry=rel,
                            limit=_MAX_ENTRY_BYTES,
                        )
                        return None
                    raw = _read_capped(zf, info, min(_MAX_ENTRY_BYTES, budget))
                    if raw is None:
                        log.warning(
                            "clawhub.fetch_zip_bomb_blocked", identifier=identifier, entry=rel
                        )
                        return None
                    budget -= len(raw)
                    try:
                        files[rel] = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        if rel == "SKILL.md":
                            log.warning("clawhub.fetch_bad_skill_encoding", identifier=identifier)
                            return None
                        files[rel] = raw
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, zlib.error, EOFError) as exc:
            # A hostile archive must fail closed, not raise through the installer:
            # an unsupported compress_type, an entry flagged encrypted, or a
            # truncated deflate stream each surface as something other than
            # BadZipFile. Might also be raw SKILL.md content — validate frontmatter.
            if text_body.strip().startswith("---"):
                files["SKILL.md"] = text_body
            else:
                log.warning(
                    "clawhub.fetch_invalid_content",
                    identifier=identifier,
                    size=len(content),
                    error=str(exc),
                )
                return None

        if "SKILL.md" not in files:
            return None

        return SkillBundle(name=identifier, files=files)

    async def inspect(self, identifier: str) -> SkillMeta | None:
        import httpx

        url = f"{self._base_url}/api/v1/skills/{identifier}"
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=_trust_env()) as client:
                resp = await client.get(url, headers=self._headers())
                resp.raise_for_status()
                item = resp.json()
        except Exception as exc:
            log.warning("clawhub.inspect_failed", identifier=identifier, error=str(exc))
            return None

        return SkillMeta(
            name=item.get("name", item.get("slug", identifier)),
            description=item.get("description") or "",
            version=item.get("version", ""),
            author=item.get("author", ""),
            source_id=self.source_id,
            trust_level=self.trust_level,
            identifier=identifier,
            homepage=item.get("homepage", ""),
            license=item.get("license", ""),
            tags=item.get("tags", []),
        )
