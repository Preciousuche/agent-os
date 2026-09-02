"""Issue #678: ``agentos sessions export`` must not write outside the CWD.

The gateway round-trip is stubbed at ``_with_client`` — these tests cover
default-filename derivation, where the user-supplied ``session_id`` reaches
the filesystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from agentos.cli import sessions_cmd
from agentos.session.manager import _safe_archive_part

runner = CliRunner()


class _FakeClient:
    async def resolve_session(self, session_id: str) -> dict[str, Any]:
        return {"session_key": session_id, "status": "done", "model": "gpt-x"}

    async def preview_sessions(self, keys: list[str]) -> dict[str, Any]:
        return {"previews": [{"lastMessage": "hello"}]}

    async def session_history(self, key: str, limit: int = 1000) -> dict[str, Any]:
        return {"messages": []}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    fake = _FakeClient()

    async def _with_client(action: Any) -> Any:
        return await action(fake)

    monkeypatch.setattr(sessions_cmd, "_with_client", _with_client)
    return fake


@pytest.mark.parametrize(
    ("session_id", "expected"),
    [
        ("agent:main:cli:aaa", "agent-main-cli-aaa"),
        ("../../etc/pwned", "etc-pwned"),
        ("..\\..\\Windows\\pwned", "Windows-pwned"),
        ("/absolute/path", "absolute-path"),
        ("..", "session"),
        (".", "session"),
        ("", "session"),
        ("---session---", "session"),
        ("session.v1", "session.v1"),
        ("my_session", "my_session"),
    ],
)
def test_safe_archive_part_sanitizes_path_separators(session_id: str, expected: str) -> None:
    """_safe_archive_part strips invalid chars and traversal tokens."""
    assert _safe_archive_part(session_id) == expected


def test_export_writes_inside_the_working_directory(
    client: _FakeClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A traversal id lands in the CWD under a sanitized name without directory traversal."""
    monkeypatch.chdir(tmp_path)
    escaped = tmp_path.parent / "pwned.json"

    result = runner.invoke(sessions_cmd.app, ["export", "../pwned", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert not escaped.exists()
    assert (tmp_path / "pwned.json").exists()


def test_export_honours_an_explicit_output_path(
    client: _FakeClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit --output path is left untouched as caller's intent."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "nested" / "custom.md"
    target.parent.mkdir()

    result = runner.invoke(
        sessions_cmd.app, ["export", "agent:main:cli:aaa", "--output", str(target)]
    )

    assert result.exit_code == 0, result.output
    assert target.exists()
