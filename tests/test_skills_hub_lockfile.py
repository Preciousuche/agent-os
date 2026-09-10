"""Lockfile.save/load atomicity and Lockfile.update's read-modify-write lock.

Issue #1557: ``Lockfile.load``/``.save`` were a whole-file JSON read and a
whole-file ``write_text`` with no locking of any kind. ``SkillInstaller``
called ``load() -> mutate() -> save()`` per install/uninstall; two overlapping
calls could load before either had saved, so the later ``save()`` overwrote
the file wholesale and silently dropped the earlier caller's entry.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agentos.skills.hub.lockfile import LockEntry, Lockfile, _lock_for


@pytest.mark.asyncio
async def test_lock_for_serializes_access_to_the_same_path(tmp_path: Path) -> None:
    """The lock keyed to one path must never let two holders' critical
    sections overlap, regardless of scheduling order."""
    path = tmp_path / "lock.json"
    events: list[str] = []

    async def worker(tag: str, hold: float) -> None:
        async with _lock_for(path):
            events.append(f"{tag}:enter")
            await asyncio.sleep(hold)
            events.append(f"{tag}:exit")

    await asyncio.gather(worker("a", 0.02), worker("b", 0.0))

    # Whichever ran first, its enter/exit pair must be contiguous — the other
    # worker's "enter" never lands between them.
    assert events[0].endswith("enter")
    assert events[1].endswith("exit")
    assert events[0].split(":")[0] == events[1].split(":")[0]


@pytest.mark.asyncio
async def test_lock_for_does_not_serialize_different_paths(tmp_path: Path) -> None:
    """Two different lockfile paths (e.g. two AGENTOS_HOME roots in tests)
    must not contend with each other's lock."""
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    order: list[str] = []
    released_a = asyncio.Event()

    async def hold_a() -> None:
        async with _lock_for(path_a):
            order.append("a:enter")
            await released_a.wait()
            order.append("a:exit")

    async def touch_b() -> None:
        async with _lock_for(path_b):
            order.append("b:enter")
            order.append("b:exit")
        released_a.set()

    await asyncio.gather(hold_a(), touch_b())

    # b completed fully while a was still holding its own lock.
    assert order.index("b:enter") < order.index("a:exit")


@pytest.mark.asyncio
async def test_update_persists_the_mutation(tmp_path: Path) -> None:
    path = tmp_path / "lock.json"

    def _mutate(lf: Lockfile) -> bool:
        lf.add("demo", LockEntry(source="s", identifier="demo"))
        return True

    changed = await Lockfile.update(path, _mutate)

    assert changed is True
    assert Lockfile.load(path).get("demo") is not None


@pytest.mark.asyncio
async def test_update_skips_the_write_when_mutate_reports_no_change(tmp_path: Path) -> None:
    """remove() of a name that was never installed must not rewrite the file
    with "no news" — it returns False and update() leaves the file alone."""
    path = tmp_path / "lock.json"

    changed = await Lockfile.update(path, lambda lf: lf.remove("never-installed"))

    assert changed is False
    assert not path.exists()


@pytest.mark.asyncio
async def test_two_concurrent_updates_to_different_skills_both_survive(
    tmp_path: Path,
) -> None:
    """Issue #1557's exact reproduction: two concurrent installs of different
    skills, each doing load -> mutate -> save, must not clobber each other."""
    path = tmp_path / "lock.json"

    async def install(name: str) -> None:
        def _mutate(lf: Lockfile) -> bool:
            lf.add(name, LockEntry(source="s", identifier=name))
            return True

        await Lockfile.update(path, _mutate)

    await asyncio.gather(*(install(f"skill-{i}") for i in range(10)))

    installed = Lockfile.load(path).installed
    assert set(installed.keys()) == {f"skill-{i}" for i in range(10)}


def test_save_writes_valid_json_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "lock.json"
    lf = Lockfile()
    lf.add("demo", LockEntry(source="s", identifier="demo"))

    lf.save(path)

    assert lf.get("demo") is not None
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["installed"]["demo"]["identifier"] == "demo"


def test_save_leaves_no_leftover_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "lock.json"
    Lockfile().save(path)

    leftovers = list(path.parent.glob(f".{path.name}.*.tmp"))
    assert leftovers == []
