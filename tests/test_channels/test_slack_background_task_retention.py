"""Slack's interactive-payload dispatch must retain its background task
(#1033): both _handle_socket_frame (Socket Mode) and _handle_webhook (HTTP)
spawned it via a bare asyncio.create_task(...) with no reference kept, so
the event loop was free to garbage collect it mid-execution and silently
drop the approval/deny click.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import quote

import pytest
from starlette.requests import Request

import agentos.channels.slack as slack_module
from agentos.channels.slack import SlackChannel

_SIGNING_SECRET = "s3cr3t"


def _spy_on_create_background_task(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Wrap the real create_background_task so calls are recorded but the
    task still actually runs, then patch it into the slack module's own
    namespace (where the import binds it) rather than the source module."""
    calls: list[Any] = []
    real = slack_module.create_background_task

    def spy(coro: Any, **kwargs: Any) -> Any:
        calls.append(coro)
        return real(coro, **kwargs)

    monkeypatch.setattr(slack_module, "create_background_task", spy)
    return calls


@pytest.mark.asyncio
async def test_socket_frame_interactive_dispatch_uses_background_task_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = SlackChannel(token="xoxb-test", slack_channel_id="")
    handled: list[dict] = []

    async def fake_handle_interactive(payload: dict) -> None:
        handled.append(payload)

    monkeypatch.setattr(channel, "_handle_slack_interactive", fake_handle_interactive)
    calls = _spy_on_create_background_task(monkeypatch)

    class _FakeSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, payload: str) -> None:
            self.sent.append(payload)

    ws = _FakeSocket()
    await channel._handle_socket_frame(
        ws,
        (
            '{"envelope_id":"env-interactive","type":"interactive","payload":'
            '{"type":"block_actions"}}'
        ),
    )
    # The frame handler only schedules the background task; give it a turn
    # of the loop to actually run before asserting on its side effect.
    await asyncio.sleep(0)

    assert ws.sent == ['{"envelope_id": "env-interactive"}']
    assert len(calls) == 1
    assert handled == [{"type": "block_actions"}]


@pytest.mark.asyncio
async def test_webhook_interactive_dispatch_uses_background_task_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = SlackChannel(token="xoxb-test", slack_channel_id="", signing_secret=_SIGNING_SECRET)
    handled: list[dict] = []

    async def fake_handle_interactive(payload: dict) -> None:
        handled.append(payload)

    monkeypatch.setattr(channel, "_handle_slack_interactive", fake_handle_interactive)
    calls = _spy_on_create_background_task(monkeypatch)

    inner_payload = {"type": "block_actions"}
    body = f"payload={quote(json.dumps(inner_payload))}".encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(
        _SIGNING_SECRET.encode(),
        f"v0:{timestamp}:{body.decode()}".encode(),
        hashlib.sha256,
    ).hexdigest()

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"x-slack-request-timestamp", timestamp.encode()),
            (b"x-slack-signature", f"v0={digest}".encode()),
        ],
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(scope, receive=receive)

    response = await channel._handle_webhook(request)
    await asyncio.sleep(0)

    assert response.status_code == 200
    assert len(calls) == 1
    assert handled == [inner_payload]
