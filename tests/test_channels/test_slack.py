from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentos.channels.contract import ChannelSendStatus
from agentos.channels.slack import SlackChannel
from agentos.channels.types import OutgoingMessage


class _FakeResp:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "https://slack.com"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture(autouse=True)
def mock_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(delay: float) -> None:
        pass

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


@pytest.mark.asyncio
async def test_slack_send_retries_on_transient_http_errors() -> None:
    call_count = 0

    class FakeClient:
        async def post(self, path: str, **kwargs: Any) -> _FakeResp:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return _FakeResp(503, {"ok": False, "error": "server_error"})
            return _FakeResp(200, {"ok": True, "ts": "123.456"})

    channel = SlackChannel(token="xoxb-test", slack_channel_id="C-default")
    channel._client = FakeClient()  # type: ignore[assignment]

    msg = OutgoingMessage(content="Hello", reply_to="C-default")
    await channel.send(msg)
    assert call_count == 3


@pytest.mark.asyncio
async def test_slack_send_retries_on_rate_limit() -> None:
    call_count = 0

    class FakeClient:
        async def post(self, path: str, **kwargs: Any) -> _FakeResp:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _FakeResp(429, {"ok": False, "error": "rate_limited"})
            return _FakeResp(200, {"ok": True, "ts": "123.456"})

    channel = SlackChannel(token="xoxb-test", slack_channel_id="C-default")
    channel._client = FakeClient()  # type: ignore[assignment]

    msg = OutgoingMessage(content="Hello", reply_to="C-default")
    await channel.send(msg)
    assert call_count == 2


@pytest.mark.asyncio
async def test_slack_send_retries_on_read_timeout() -> None:
    call_count = 0

    class FakeClient:
        async def post(self, path: str, **kwargs: Any) -> _FakeResp:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ReadTimeout("Timeout")
            return _FakeResp(200, {"ok": True, "ts": "123.456"})

    channel = SlackChannel(token="xoxb-test", slack_channel_id="C-default")
    channel._client = FakeClient()  # type: ignore[assignment]

    msg = OutgoingMessage(content="Hello", reply_to="C-default")
    await channel.send(msg)
    assert call_count == 2


@pytest.mark.asyncio
async def test_slack_send_raises_fatal_error_immediately() -> None:
    call_count = 0

    class FakeClient:
        async def post(self, path: str, **kwargs: Any) -> _FakeResp:
            nonlocal call_count
            call_count += 1
            return _FakeResp(400, {"ok": False, "error": "bad_payload"})

    channel = SlackChannel(token="xoxb-test", slack_channel_id="C-default")
    channel._client = FakeClient()  # type: ignore[assignment]

    msg = OutgoingMessage(content="Hello", reply_to="C-default")
    with pytest.raises(httpx.HTTPStatusError):
        await channel.send(msg)
    assert call_count == 1


@pytest.mark.asyncio
async def test_slack_send_file_resets_file_pointer_on_retry(tmp_path: Path) -> None:
    file_path = tmp_path / "test.txt"
    file_path.write_text("file content", encoding="utf-8")

    upload_attempts = 0

    class FakeClient:
        async def post(self, path: str, **kwargs: Any) -> _FakeResp:
            nonlocal upload_attempts
            if path == "/files.getUploadURLExternal":
                return _FakeResp(
                    200,
                    {"ok": True, "upload_url": "https://upload.test", "file_id": "F1"},
                )
            elif path == "https://upload.test":
                upload_attempts += 1
                files = kwargs.get("files")
                assert files is not None
                fileobj = files["file"][1]
                content = fileobj.read()
                if upload_attempts == 1:
                    raise httpx.ReadTimeout("Upload Timeout")
                assert content == b"file content"
                return _FakeResp(200, {"ok": True})
            elif path == "/files.completeUploadExternal":
                return _FakeResp(200, {"ok": True, "files": [{"id": "F1"}]})
            return _FakeResp(400, {"ok": False})

    channel = SlackChannel(token="xoxb-test", slack_channel_id="C-default")
    channel._client = FakeClient()  # type: ignore[assignment]

    result = await channel.send_file("C-target", str(file_path), content="done")
    assert result.status == ChannelSendStatus.SENT
    assert upload_attempts == 2
