from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from agentos.channels.msteams import (
    _MAX_CONVERSATION_CACHE_BYTES,
    MSTeamsChannel,
    MSTeamsChannelConfig,
)


def test_msteams_load_cache_nonexistent_file(tmp_path: Path) -> None:
    config = MSTeamsChannelConfig(workspace_dir=str(tmp_path))
    channel = MSTeamsChannel(config)

    channel._load_conversation_cache()

    assert channel._references == {}


def test_msteams_load_cache_rejects_oversized_file(tmp_path: Path) -> None:
    config = MSTeamsChannelConfig(workspace_dir=str(tmp_path))
    channel = MSTeamsChannel(config)

    cache_file = tmp_path / "state" / "msteams" / "conversations.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    # Write a file that exceeds the 1 MB limit
    oversized_data = b" " * (_MAX_CONVERSATION_CACHE_BYTES + 10)
    cache_file.write_bytes(oversized_data)

    channel._load_conversation_cache()

    assert channel._references == {}


def test_msteams_load_cache_corrupted_json(tmp_path: Path) -> None:
    config = MSTeamsChannelConfig(workspace_dir=str(tmp_path))
    channel = MSTeamsChannel(config)

    cache_file = tmp_path / "state" / "msteams" / "conversations.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("{not valid json", encoding="utf-8")

    channel._load_conversation_cache()

    assert channel._references == {}


def test_msteams_load_cache_schema_mismatch(tmp_path: Path) -> None:
    config = MSTeamsChannelConfig(workspace_dir=str(tmp_path))
    channel = MSTeamsChannel(config)

    cache_file = tmp_path / "state" / "msteams" / "conversations.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")

    channel._load_conversation_cache()

    assert channel._references == {}


def test_msteams_load_cache_valid_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = MSTeamsChannelConfig(workspace_dir=str(tmp_path))
    channel = MSTeamsChannel(config)

    cache_file = tmp_path / "state" / "msteams" / "conversations.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "conversations": {
                    "conv-1": {"activity_id": "act-123"},
                },
            }
        ),
        encoding="utf-8",
    )

    class _MockRef:
        def deserialize(self, d: dict) -> dict:
            return d

    mock_schema = types.ModuleType("botbuilder.schema")
    mock_schema.ConversationReference = _MockRef  # type: ignore[attr-defined]
    mock_botbuilder = types.ModuleType("botbuilder")
    mock_botbuilder.schema = mock_schema  # type: ignore[attr-defined]

    monkeypatch.setitem(__import__("sys").modules, "botbuilder", mock_botbuilder)
    monkeypatch.setitem(__import__("sys").modules, "botbuilder.schema", mock_schema)

    channel._load_conversation_cache()

    assert channel._references == {"conv-1": {"activity_id": "act-123"}}
