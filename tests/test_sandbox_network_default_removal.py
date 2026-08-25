"""Removing sandbox.network_default must not break installs that set it.

The key was a silent no-op: no code read it, and its only non-default value
(proxy_allowlist) is unimplemented on both sandbox backends (seatbelt and
bubblewrap raise SandboxBackendError on PROXY_ALLOWLIST). The deprecated-field
migration drops the key so existing agentos.toml files keep loading.
"""

from __future__ import annotations

from pathlib import Path

from agentos.gateway.config import GatewayConfig


def test_an_existing_config_with_network_default_still_loads(tmp_path: Path):
    config_path = tmp_path / "agentos.toml"
    config_path.write_text(
        "[sandbox]\n"
        "sandbox = true\n"
        "network_default = \"proxy_allowlist\"\n",
        encoding="utf-8",
    )

    config = GatewayConfig.load(config_path)

    assert config.sandbox.sandbox is True
    assert not hasattr(config.sandbox, "network_default")


def test_the_dropped_key_is_reported_not_silently_eaten():
    from agentos.gateway.config_migration import DEPRECATED_SANDBOX_FIELDS

    assert "sandbox.network_default" in DEPRECATED_SANDBOX_FIELDS


def test_a_config_without_the_key_is_unaffected(tmp_path: Path):
    config_path = tmp_path / "agentos.toml"
    config_path.write_text(
        "[sandbox]\nsandbox = true\ndenial_threshold = 5\n",
        encoding="utf-8",
    )

    cfg = GatewayConfig.load(config_path)
    assert cfg.sandbox.sandbox is True
    assert cfg.sandbox.denial_threshold == 5
