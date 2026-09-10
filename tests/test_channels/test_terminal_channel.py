"""TerminalChannel.receive() on Windows vs POSIX.

Issue #1575: TerminalChannel._get_reader called loop.connect_read_pipe on
sys.stdin, which the default Windows ProactorEventLoop tries to register
with IOCP. An interactive console handle is not overlapped-capable, so that
registration raised OSError: [WinError 6] The handle is invalid and
permanently broke the reader. Windows now reads stdin via
loop.run_in_executor(None, sys.stdin.readline) instead, the same pattern
send()/edit() in this class already use for stdout.
"""

from __future__ import annotations

import sys

import pytest

from agentos.channels.terminal import TerminalChannel


class _FakeStreamReader:
    """Stand-in for the asyncio.StreamReader the POSIX path would build."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


@pytest.mark.asyncio
async def test_receive_uses_executor_readline_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Windows path must never touch connect_read_pipe / _get_reader —
    that is exactly the call that raises WinError 6."""
    monkeypatch.setattr(sys, "platform", "win32")
    lines = iter(["hello world\n", "second line\n"])

    class _FakeStdin:
        def readline(self) -> str:
            return next(lines)

    monkeypatch.setattr(sys, "stdin", _FakeStdin())
    channel = TerminalChannel()

    async def _get_reader_should_not_be_called() -> _FakeStreamReader:
        raise AssertionError("_get_reader (connect_read_pipe) must not run on Windows")

    monkeypatch.setattr(channel, "_get_reader", _get_reader_should_not_be_called)

    first = await channel.receive()
    second = await channel.receive()

    assert first.content == "hello world"
    assert second.content == "second line"
    assert first.sender_id == "user"
    assert first.channel_id == "terminal"


@pytest.mark.asyncio
async def test_receive_reports_eof_as_empty_content_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    class _EofStdin:
        def readline(self) -> str:
            return ""

    monkeypatch.setattr(sys, "stdin", _EofStdin())
    channel = TerminalChannel()

    message = await channel.receive()

    assert message.content == ""


@pytest.mark.asyncio
async def test_receive_still_uses_the_stream_reader_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-Windows platforms keep the original connect_read_pipe-backed
    reader — this fix is additive, not a platform-wide behavior change."""
    monkeypatch.setattr(sys, "platform", "linux")
    channel = TerminalChannel()
    fake_reader = _FakeStreamReader([b"posix line\n"])

    async def _fake_get_reader() -> _FakeStreamReader:
        return fake_reader

    monkeypatch.setattr(channel, "_get_reader", _fake_get_reader)

    message = await channel.receive()

    assert message.content == "posix line"
