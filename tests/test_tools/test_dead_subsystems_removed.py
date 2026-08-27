"""Regression guard for the dead subsystems retired in issue #362.

Each of these shipped in the wheel while being dead or permanently-failing:
the ``onboard_agent`` wizard (no caller, no side effect), the ``canvas`` /
``nodes`` tools (whose only behaviour was to raise), and the no-op
``filter_by_profile`` / ``profile_allows_tool`` helpers that made
``visibility.py`` read like a second home for profile enforcement. This test
keeps them from creeping back.
"""

from __future__ import annotations

import importlib

import pytest

from agentos.tools.types import CallerKind, ToolContext


@pytest.mark.parametrize(
    "module",
    [
        "agentos.application.wizard",
        "agentos.application.wizard_rpc",
        "agentos.gateway.wizard",
        "agentos.gateway.rpc_wizard",
        "agentos.tools.builtin.nodes",
    ],
)
def test_dead_modules_are_gone(module: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_wizard_rpc_methods_are_not_registered() -> None:
    from agentos.gateway.rpc import get_dispatcher

    assert [m for m in get_dispatcher().methods() if m.startswith("wizard.")] == []


def test_node_runtime_tools_are_not_registered() -> None:
    import agentos.tools.builtin  # noqa: F401
    from agentos.tools.registry import get_default_registry

    assert {"canvas", "nodes"}.isdisjoint(get_default_registry().list_names())


def test_visibility_no_longer_offers_pass_through_profile_helpers() -> None:
    from agentos.tools import registry, visibility

    for name in ("filter_by_profile", "profile_allows_tool"):
        assert not hasattr(visibility, name)
        assert not hasattr(registry, name)


def test_profile_enforcement_has_a_single_home() -> None:
    from agentos.tools import policy
    from agentos.tools.policy.chain import POLICY_CHAIN

    assert not hasattr(policy, "ProfilePolicy")
    assert "profile" not in {check.name for check in POLICY_CHAIN}


def test_resolve_profile_survives_as_the_one_profile_seam() -> None:
    from agentos.tools.registry import ToolProfile, resolve_profile

    assert resolve_profile(ToolContext(caller_kind=CallerKind.AGENT)) is ToolProfile.CONFIGURED
