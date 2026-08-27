from __future__ import annotations

import importlib.util

from agentos.channels.contract import PUBLIC_VENDOR_ADAPTERS
from agentos.dist.workspace_state import (
    BUNDLED_CHANNELS,
    BUNDLED_TOOLS,
    build_workspace_state,
)


def test_bundled_channels_are_importable_adapter_modules() -> None:
    missing = [
        name
        for name in BUNDLED_CHANNELS
        if importlib.util.find_spec(f"agentos.channels.{name}") is None
    ]

    assert missing == []


def test_workspace_state_does_not_advertise_unshipped_or_retired_channels() -> None:
    state = build_workspace_state()

    assert {
        "dingtalk",
        "matrix",
        "qq",
        "qqbot",
        "wecom",
        "whatsapp",
    }.isdisjoint(state["bundled_channels"])


def test_workspace_state_channel_inventory_matches_public_and_internal_adapters() -> None:
    expected = tuple(sorted((*PUBLIC_VENDOR_ADAPTERS, "terminal", "websocket")))

    assert tuple(sorted(BUNDLED_CHANNELS)) == expected


def test_bundled_tools_are_importable_builtin_modules() -> None:
    """Every advertised built-in must still ship in the wheel.

    ``agentos dist`` publishes BUNDLED_TOOLS as the install inventory operators
    diff across releases, so a name that outlives its module reads as live
    capability. ``nodes`` and ``agent`` both did until issue #362.
    """
    missing = [
        name
        for name in BUNDLED_TOOLS
        if importlib.util.find_spec(f"agentos.tools.builtin.{name}") is None
    ]

    assert missing == []
