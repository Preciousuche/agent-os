"""Transient-HTTP retries on the Discord adapter's send_file (#1164).

DiscordChannel.send_file opened the upload file handle *outside*
retry_request and passed the same (already-consumed) file object into every
attempt. On a retry -- most commonly a 429 rate limit, Discord's single
likeliest retry trigger -- the second attempt's f.read() returned b"" and
httpx silently uploaded an empty body; nothing raised, since the empty
upload itself returns 200. SlackChannel.send_file already reopens the file
per attempt inside the closure passed to retry_request; this mirrors that
shape for Discord.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agentos.channels.discord import DiscordChannel, DiscordChannelConfig

_REQUEST = httpx.Request("POST", "https://discord.test/api")


def _resp(status_code: int = 200, body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=body if body is not None else {"id": "msg-1"},
        request=_REQUEST,
    )


def _channel() -> DiscordChannel:
    return DiscordChannel(DiscordChannelConfig(token="t"))


@pytest.fixture
def no_sleep():
    """Collapse retry_request's backoff so the assertions stay fast."""
    with patch("agentos.channels._util.asyncio.sleep", new=AsyncMock()) as sleep:
        yield sleep


async def test_send_file_retries_and_reopens_the_upload_body(tmp_path: Path, no_sleep) -> None:
    """A retried upload must re-read the file, not send an exhausted handle.

    Asserting on the bytes actually read on each attempt (not just an
    open()/reopen call count) is the point: a handle that was merely
    rewound rather than reopened would still pass a weaker assertion.
    """
    sample = tmp_path / "note.txt"
    sample.write_bytes(b"hello world")

    channel = _channel()
    bodies: list[bytes] = []

    async def _post(url: str, **kwargs: Any) -> httpx.Response:
        bodies.append(kwargs["files"]["file"][1].read())
        if len(bodies) == 1:
            return _resp(503)
        return _resp(200, {"id": "msg-1"})

    client = AsyncMock()
    client.post = AsyncMock(side_effect=_post)
    channel._client = client

    result = await channel.send_file("C123", str(sample), content="here")

    assert result.provider_message_id == "msg-1"
    # Both attempts carried the full body -- the handle was reopened, not
    # merely retried with whatever was left of a consumed stream.
    assert bodies == [b"hello world", b"hello world"]
    assert client.post.await_count == 2


async def test_send_file_retries_rate_limit_with_full_body(tmp_path: Path, no_sleep) -> None:
    """429 is Discord's single most likely retry trigger for an upload."""
    sample = tmp_path / "note.txt"
    sample.write_bytes(b"payload bytes")

    channel = _channel()
    bodies: list[bytes] = []

    async def _post(url: str, **kwargs: Any) -> httpx.Response:
        bodies.append(kwargs["files"]["file"][1].read())
        if len(bodies) == 1:
            return _resp(429)
        return _resp(200, {"id": "msg-2"})

    client = AsyncMock()
    client.post = AsyncMock(side_effect=_post)
    channel._client = client

    result = await channel.send_file("C123", str(sample))

    assert result.provider_message_id == "msg-2"
    assert bodies == [b"payload bytes", b"payload bytes"]


async def test_send_file_does_not_retry_fatal_client_error(tmp_path: Path, no_sleep) -> None:
    sample = tmp_path / "note.txt"
    sample.write_bytes(b"hello world")

    channel = _channel()
    client = AsyncMock()
    client.post = AsyncMock(return_value=_resp(403, {"message": "Missing Permissions"}))
    channel._client = client

    with pytest.raises(httpx.HTTPStatusError):
        await channel.send_file("C123", str(sample))

    assert client.post.await_count == 1
    no_sleep.assert_not_awaited()
