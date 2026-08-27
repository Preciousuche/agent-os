"""Removing daily-note char budgets must not break installs that were using them.

Two things outlive the code: the `memory.daily_note_max_chars` and
`memory.daily_notes_total_max_chars` keys in a user's agentos.toml, and the
memory-mode fingerprint that reported them as live knobs. `MemoryConfig` forbids
extra keys, so the first would fail validation at boot; the second would keep
attribution logs lying about which knobs shape behavior.
"""

from __future__ import annotations

from pathlib import Path

from agentos.gateway.config import GatewayConfig

# -- config -------------------------------------------------------------------


def test_an_existing_config_with_daily_note_keys_still_loads(tmp_path: Path):
    """The decisive case: MemoryConfig forbids extras, so this would 500 at boot."""
    config_path = tmp_path / "agentos.toml"
    config_path.write_text(
        "[memory]\n"
        "inject_limit = 6400\n"
        "daily_note_max_chars = 8000\n"
        "daily_notes_total_max_chars = 16000\n",
        encoding="utf-8",
    )

    config = GatewayConfig.load(config_path)

    assert config.memory.inject_limit == 6400
    assert not hasattr(config.memory, "daily_note_max_chars")
    assert not hasattr(config.memory, "daily_notes_total_max_chars")


def test_the_dropped_keys_are_reported_not_silently_eaten():
    from agentos.gateway.config_migration import DEPRECATED_MEMORY_FIELDS

    assert "memory.daily_note_max_chars" in DEPRECATED_MEMORY_FIELDS
    assert "memory.daily_notes_total_max_chars" in DEPRECATED_MEMORY_FIELDS


def test_a_config_without_daily_note_keys_is_unaffected(tmp_path: Path):
    config_path = tmp_path / "agentos.toml"
    config_path.write_text("[memory]\ninject_limit = 5000\n", encoding="utf-8")

    assert GatewayConfig.load(config_path).memory.inject_limit == 5000


def test_the_fingerprint_no_longer_carries_daily_note_keys():
    fingerprint = GatewayConfig().memory_mode_fingerprint()
    assert "daily_note_max_chars" not in fingerprint
    assert "daily_notes_total_max_chars" not in fingerprint
