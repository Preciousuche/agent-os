"""Every CLI surface that opens its own gateway connection must send the token.

Regression guard. ``resolve_auth`` grants no loopback exemption in token mode:
once ``auth.mode = "token"`` is set, a connection that omits the token is
refused even on a purely local install. ``chat``, ``sessions``, ``skills``, and
``env`` each opened a connection by hand and skipped the token that
``default_gateway_token`` already resolves — so turning auth on broke four
commands that had nothing to do with remote access.

The fake client below takes ``url`` as a *required* positional argument on
purpose: the original ``chat`` bug was a bare ``client.connect()`` that
silently fell back to the hardcoded ``ws://localhost:18791/ws`` default.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentos.cli import env_cmd, gateway_client, sessions_cmd, skills_cmd
from agentos.cli.chat import gateway_runtime

_TOKEN = "token-from-env"
_HOST = "10.0.0.5"


class _StopError(Exception):
    """Unwind a runtime once the connection under test has been recorded."""


@pytest.fixture
def connections(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    class _FakeClient:
        async def connect(self, url: str, *, token: str | None = None) -> None:
            seen.append({"url": url, "token": token})

        async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            return {}

        async def create_session(self, **kwargs: Any) -> str:
            raise _StopError

        async def close(self) -> None:
            return None

    monkeypatch.setenv("AGENTOS_GATEWAY_URL", f"ws://{_HOST}:18791/ws")
    monkeypatch.setenv("AGENTOS_GATEWAY_TOKEN", _TOKEN)
    monkeypatch.setattr(gateway_client, "GatewayClient", _FakeClient)
    return seen


def _assert_authenticated(seen: list[dict[str, Any]]) -> None:
    assert len(seen) == 1
    assert _HOST in seen[0]["url"]
    assert seen[0]["token"] == _TOKEN


class TestGatewayConnectionsCarryTheToken:
    def test_env_cmd(self, connections: list[dict[str, Any]]) -> None:
        import asyncio

        asyncio.run(env_cmd._try_gateway("env.list", {}, json_output=False))

        _assert_authenticated(connections)

    def test_skills_cmd(self, connections: list[dict[str, Any]]) -> None:
        import asyncio

        asyncio.run(skills_cmd._try_gateway_skill_mutation("skills.list", {}, json_output=False))

        _assert_authenticated(connections)

    def test_sessions_cmd(self, connections: list[dict[str, Any]]) -> None:
        import asyncio

        async def _action(client: Any) -> dict[str, Any]:
            return await client.call("sessions.list", {})

        asyncio.run(sessions_cmd._with_client(_action))

        _assert_authenticated(connections)

    def test_chat_runtime(self, connections: list[dict[str, Any]]) -> None:
        import asyncio

        deps = gateway_runtime.GatewayRuntimeDependencies(
            stream_response=None,  # type: ignore[arg-type]
            handle_slash_command=None,  # type: ignore[arg-type]
            run_input_loop=None,  # type: ignore[arg-type]
            get_tui_output=lambda scope: None,
            is_exit_command=lambda text: False,
            notify=lambda notice: None,
        )

        with pytest.raises(_StopError):
            asyncio.run(gateway_runtime.run_gateway_chat(model=None, session_id=None, deps=deps))

        _assert_authenticated(connections)
