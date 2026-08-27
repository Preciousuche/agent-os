"""AgentSubagentDefaults round-trips and exposes documented semantics."""

from __future__ import annotations

from pathlib import Path

from agentos.gateway.config import (
    AgentDefaults,
    AgentEntryConfig,
    AgentSubagentDefaults,
    GatewayConfig,
    SubagentsGatewayConfig,
)


def test_subagent_defaults_optional_fields_default_to_none() -> None:
    d = AgentSubagentDefaults()
    assert d.model is None
    assert d.max_children_per_session is None
    assert d.allow_agents is None
    assert d.cascade_on_parent_kill is True


def test_allow_agents_distinguishes_unset_self_only_and_wildcard() -> None:
    unset = AgentSubagentDefaults()
    self_only = AgentSubagentDefaults(allow_agents=[])
    wildcard = AgentSubagentDefaults(allow_agents=["*"])

    # Round-trip via model_dump preserves the three distinct shapes
    assert unset.model_dump()["allow_agents"] is None
    assert self_only.model_dump()["allow_agents"] == []
    assert wildcard.model_dump()["allow_agents"] == ["*"]


def test_agent_entry_carries_optional_subagents_block() -> None:
    bare = AgentEntryConfig(id="research")
    assert bare.subagents is None

    configured = AgentEntryConfig(
        id="research",
        subagents=AgentSubagentDefaults(model="haiku", max_children_per_session=5),
    )
    assert configured.subagents is not None
    assert configured.subagents.model == "haiku"
    assert configured.subagents.max_children_per_session == 5


def test_gateway_config_exposes_agents_defaults_and_subagents_subtree() -> None:
    cfg = GatewayConfig()
    # Defaults exist and are additive — current behavior preserved.
    assert isinstance(cfg.agents_defaults, AgentDefaults)
    assert cfg.agents_defaults.subagents is None  # unset → no global override
    assert isinstance(cfg.subagents, SubagentsGatewayConfig)
    assert cfg.subagents.enforce_disabled_agents is False
    assert cfg.subagents.subagent_reserved_slots == 2


def test_gateway_config_accepts_explicit_subagent_defaults() -> None:
    cfg = GatewayConfig(
        agents_defaults=AgentDefaults(subagents=AgentSubagentDefaults(model="haiku")),
        subagents=SubagentsGatewayConfig(
            enforce_disabled_agents=True,
            subagent_reserved_slots=4,
        ),
    )
    assert cfg.agents_defaults.subagents is not None
    assert cfg.agents_defaults.subagents.model == "haiku"
    assert cfg.subagents.enforce_disabled_agents is True
    assert cfg.subagents.subagent_reserved_slots == 4


def test_legacy_subagents_config_with_archive_after_minutes_still_loads(
    tmp_path: Path,
) -> None:
    """SubagentsGatewayConfig does not set extra='forbid', but the migration
    should still strip the dead key and rewrite the file with a backup."""
    config_path = tmp_path / "agentos.toml"
    config_path.write_text(
        "[subagents]\narchive_after_minutes = 60\nenforce_disabled_agents = true\n",
        encoding="utf-8",
    )

    cfg = GatewayConfig.load(config_path)

    assert cfg.subagents.enforce_disabled_agents is True
    assert not hasattr(cfg.subagents, "archive_after_minutes")
    backups = sorted(tmp_path.glob("agentos.toml.backup.*"))
    assert backups
    backup_text = backups[-1].read_text(encoding="utf-8")
    assert "archive_after_minutes" in backup_text
    text = config_path.read_text(encoding="utf-8")
    assert "archive_after_minutes" not in text
    assert "enforce_disabled_agents" in text


def test_the_dropped_archive_key_is_reported_not_silently_eaten():
    from agentos.gateway.config_migration import DEPRECATED_SUBAGENTS_FIELDS

    assert "subagents.archive_after_minutes" in DEPRECATED_SUBAGENTS_FIELDS
