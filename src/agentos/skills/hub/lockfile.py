"""Lockfile management for installed skills."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agentos.memory.atomic_write import atomic_write_text
from agentos.paths import default_agentos_home

#: One asyncio.Lock per resolved lockfile path, so concurrent installs that
#: each do load -> mutate -> save race on the same in-memory lock instead of
#: each racing the filesystem independently. Keyed by path (not a single
#: global lock) so tests and multiple AGENTOS_HOME roots pointing at
#: different lockfiles don't serialize against each other.
_locks: dict[str, asyncio.Lock] = {}


def _lock_for(path: Path) -> asyncio.Lock:
    key = str(path.resolve())
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def default_lockfile_path() -> Path:
    """Return the shared skills lockfile path.

    Installer, CLI, and the Installed inventory must read the same file; each
    of them deriving it separately is how they drift apart.
    """
    return default_agentos_home() / "skills-lock.json"


@dataclass
class LockEntry:
    """A single installed skill entry in the lockfile."""

    source: str
    identifier: str
    version: str = ""
    installed_at: str = ""
    path: str = ""
    sha256: str = ""
    license: str = ""
    upstream_url: str = ""
    #: Publisher slug the installing catalog row claimed. A *selector*, not a
    #: description: it is looked up in the server-side allowlist
    #: (:func:`agentos.skills.publishers.resolve_publisher`) before anything is
    #: displayed, so a hub cannot mint brand identity by naming itself here any
    #: more than a ``SKILL.md`` can.
    publisher_id: str = ""
    #: Raw ``provider`` string from the catalog row, kept for diagnostics —
    #: it tells an operator which brand an *unrecognized* publisher claimed to
    #: be. Never rendered as branding; only :attr:`publisher_id` is resolved.
    publisher_name: str = ""
    source_trust: str = ""
    scan_verdict: str = ""
    scan_strategy: str = ""
    scan_findings: list[dict[str, str | int]] = field(default_factory=list)


@dataclass
class Lockfile:
    """Manages .agentos/skills-lock.json."""

    version: int = 1
    installed: dict[str, LockEntry] = field(default_factory=dict)

    @staticmethod
    def load(path: Path) -> Lockfile:
        if not path.exists():
            return Lockfile()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            lf = Lockfile(version=data.get("version", 1))
            # Every LockEntry field must be listed here or it is silently
            # dropped on load, however faithfully install-time wrote it.
            known_fields = {
                "source",
                "identifier",
                "version",
                "installed_at",
                "path",
                "sha256",
                "license",
                "upstream_url",
                "publisher_id",
                "publisher_name",
                "source_trust",
                "scan_verdict",
                "scan_strategy",
                "scan_findings",
            }
            for name, entry_data in data.get("installed", {}).items():
                filtered = {k: v for k, v in entry_data.items() if k in known_fields}
                lf.installed[name] = LockEntry(**filtered)
            return lf
        except (json.JSONDecodeError, TypeError, OSError):
            return Lockfile()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": self.version,
            "installed": {name: asdict(entry) for name, entry in self.installed.items()},
        }
        # A plain write_text truncates before writing the new content; a crash
        # or full disk mid-write leaves a partial file that load() then reads
        # as JSONDecodeError and silently treats as an empty lockfile. Writing
        # to a temp file and renaming into place means a reader only ever
        # sees the old content or the new content, never a truncated file.
        atomic_write_text(path, json.dumps(data, indent=2))

    @staticmethod
    async def update(path: Path, mutate: Callable[[Lockfile], bool]) -> bool:
        """Load, apply *mutate*, and save as one critical section.

        ``load() -> mutate -> save()`` done separately races: two concurrent
        callers each load before the other's save lands, and the later save
        overwrites the file wholesale, silently dropping the earlier caller's
        change. Locking only around ``save()`` does not close this — the
        ``load()`` has to be inside the same critical section, or a caller can
        still load stale data before another caller's save takes the lock.

        *mutate* returns whether it changed the lockfile; that same value is
        returned here so a caller like ``remove()`` (which is a no-op for a
        name that was never installed) can tell whether anything happened
        without also having to thread a mutable result out of the callback.
        A ``False`` return leaves the file untouched rather than rewriting it
        with no news.
        """
        async with _lock_for(path):
            lf = Lockfile.load(path)
            changed = mutate(lf)
            if changed:
                lf.save(path)
            return changed

    def add(self, name: str, entry: LockEntry) -> None:
        self.installed[name] = entry

    def remove(self, name: str) -> bool:
        if name in self.installed:
            del self.installed[name]
            return True
        return False

    def get(self, name: str) -> LockEntry | None:
        return self.installed.get(name)


def compute_sha256(directory: Path) -> str:
    """Compute SHA-256 digest of all non-dotfiles in a directory."""
    hasher = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file() and not any(p.startswith(".") for p in path.relative_to(directory).parts):
            hasher.update(str(path.relative_to(directory)).encode())
            hasher.update(path.read_bytes())
    return hasher.hexdigest()
