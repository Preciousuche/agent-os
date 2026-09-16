"""Issue #2473: bounded-registry sizes were collected but never shown.

``BoundedRegistry`` records its name, size, ceiling and eviction count, and
``registry_stats()`` returns one row per live registry. Nothing called it —
``grep -rn "registry_stats" src/agentos`` found the definition and the
``util/__init__`` re-export and no consumer — so the data reached no operator.

That matters because the defect it would reveal keeps recurring, and every
instance so far was found by reading source rather than by anyone noticing a
running gateway grow: #1084, #1098, #1131, #2399, #2445.

The stats now ride the ``diagnostics.status`` payload, which the CLI already
calls, so an operator can see per-registry size, ceiling and evictions without
a heap dump. They are reported unconditionally rather than behind the
diagnostics toggle: names and counts carry no user data, and a leak is exactly
the thing you want to see *before* turning diagnostics on.
"""

from __future__ import annotations

from agentos.gateway.diagnostics import (
    DiagnosticsState,
    diagnostics_status_payload,
    registry_snapshot,
)
from agentos.util.bounded_registry import BoundedRegistry


def test_the_payload_carries_a_registries_section() -> None:
    payload = diagnostics_status_payload(DiagnosticsState(), None)

    assert "registries" in payload
    assert "summary" in payload["registries"]


def test_the_section_is_present_whether_or_not_diagnostics_is_enabled() -> None:
    """A leak is what you want to see before switching diagnostics on, and the
    rows carry no user data, so they are not gated behind the toggle."""
    off = diagnostics_status_payload(DiagnosticsState(configured_enabled=False), None)
    on = diagnostics_status_payload(DiagnosticsState(configured_enabled=True), None)

    assert off["enabled"] is False
    assert on["enabled"] is True
    assert "registries" in off
    assert "registries" in on


def test_the_existing_payload_keys_are_untouched() -> None:
    """Additive only — the RPC shape other callers read must not shift."""
    payload = diagnostics_status_payload(DiagnosticsState(), None)

    for key in (
        "enabled",
        "detail",
        "configured",
        "runtime",
        "raw_turn_call",
        "applies_to",
        "server_debug_changed",
        "auth_scope_changed",
    ):
        assert key in payload


def test_a_live_registry_appears_with_its_numbers() -> None:
    registry: BoundedRegistry[str, int] = BoundedRegistry(
        name="test._diagnostics_probe", max_entries=4
    )
    for index in range(3):
        registry[f"k{index}"] = index

    rows = {row["name"]: row for row in registry_snapshot()["registries"]}

    assert "test._diagnostics_probe" in rows
    row = rows["test._diagnostics_probe"]
    assert row["entries"] == 3
    assert row["maxEntries"] == 4
    assert row["evictions"] == 0


def test_a_registry_at_its_ceiling_is_called_out() -> None:
    """Size alone is not the signal — a registry pinned at its ceiling with
    evictions climbing is losing state it will have to rebuild."""
    registry: BoundedRegistry[str, int] = BoundedRegistry(
        name="test._diagnostics_full", max_entries=2
    )
    for index in range(10):
        registry[f"k{index}"] = index

    snapshot = registry_snapshot()
    rows = {row["name"]: row for row in snapshot["registries"]}

    assert rows["test._diagnostics_full"]["entries"] == 2
    assert rows["test._diagnostics_full"]["evictions"] > 0
    assert "test._diagnostics_full" in snapshot["summary"]["atCeiling"]


def test_a_registry_below_its_ceiling_is_not_called_out() -> None:
    registry: BoundedRegistry[str, int] = BoundedRegistry(
        name="test._diagnostics_roomy", max_entries=100
    )
    registry["only"] = 1

    snapshot = registry_snapshot()

    assert "test._diagnostics_roomy" not in snapshot["summary"]["atCeiling"]


def test_the_summary_totals_the_rows() -> None:
    snapshot = registry_snapshot()
    rows = snapshot["registries"]

    assert snapshot["summary"]["count"] == len(rows)
    assert snapshot["summary"]["entries"] == sum(int(r["entries"]) for r in rows)
    assert snapshot["summary"]["evictions"] == sum(int(r["evictions"]) for r in rows)


def test_rows_are_sorted_by_name() -> None:
    """A stable order so an operator diffing two snapshots sees real changes
    rather than dictionary ordering."""
    names = [row["name"] for row in registry_snapshot()["registries"]]

    assert names == sorted(names)


def test_every_row_carries_the_fields_an_operator_needs() -> None:
    BoundedRegistry(name="test._diagnostics_fields", max_entries=8)

    for row in registry_snapshot()["registries"]:
        for field in ("name", "entries", "maxEntries", "evictions", "expirations"):
            assert field in row, f"{row.get('name')} is missing {field}"


def test_the_weak_table_caveat_is_stated_in_the_payload() -> None:
    """The table is a WeakSet by design, so an absent name means "not live
    now", not "zero". Saying so beats letting a reader assume."""
    note = registry_snapshot()["note"]

    assert "not live now" in note


def test_a_collected_registry_drops_out_without_erroring() -> None:
    """The weak table is the leak-avoidance property; reading it while entries
    disappear must not raise."""
    registry: BoundedRegistry[str, int] = BoundedRegistry(name="test._diagnostics_transient")
    registry["k"] = 1
    assert any(
        row["name"] == "test._diagnostics_transient" for row in registry_snapshot()["registries"]
    )

    del registry
    import gc

    gc.collect()

    snapshot = registry_snapshot()
    assert isinstance(snapshot["registries"], list)
    assert snapshot["summary"]["count"] == len(snapshot["registries"])


def test_the_snapshot_is_json_safe() -> None:
    """It goes out over JSON-RPC, so every value has to serialise."""
    import json

    json.dumps(diagnostics_status_payload(DiagnosticsState(), None))
