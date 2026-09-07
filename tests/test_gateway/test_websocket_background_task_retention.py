"""_enqueue_frame's CONTROL-overflow force-close must retain its background
task (#1033): it spawned self._force_close(...) via a bare
asyncio.create_task(...) with no reference kept, so the event loop was free
to garbage collect it before the close frame reached the client, leaving a
connection the server believes it force-closed but the client never heard
from.
"""

from __future__ import annotations

import asyncio
import gc
from typing import Any

import pytest
from starlette.websockets import WebSocketState

import agentos.gateway.websocket as websocket_module
from agentos.gateway.websocket import WsConnection


class _FakeWebSocket:
    """Minimal Starlette WebSocket stand-in, matching test_ws_writer_queue.py."""

    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.sent: list[str] = []
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self._send_event: asyncio.Event | None = None
        self._send_unblock: asyncio.Event | None = None
        self.client = None

    async def send_text(self, text: str) -> None:
        if self._send_event is not None and self._send_unblock is not None:
            self._send_event.set()
            await self._send_unblock.wait()
        self.sent.append(text)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_code = code
        self.close_reason = reason
        self.client_state = WebSocketState.DISCONNECTED


@pytest.mark.asyncio
async def test_control_overflow_force_close_uses_background_task_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    real = websocket_module.create_background_task

    def spy(coro: Any, **kwargs: Any) -> Any:
        calls.append(coro)
        return real(coro, **kwargs)

    monkeypatch.setattr(websocket_module, "create_background_task", spy)

    fake = _FakeWebSocket()
    conn = WsConnection(conn_id="cx-retain", ws=fake)  # type: ignore[arg-type]
    conn._start_writer(maxsize=4, enabled=True)

    # Block the writer's first send so the queue is not drained before it
    # overflows (same technique as test_ws_writer_queue.py).
    fake._send_event = asyncio.Event()
    fake._send_unblock = asyncio.Event()
    try:
        for i in range(4):
            await conn.send_event(
                "session.event.text_delta",
                {"chunk": str(i), "session_key": "sess-A", "stream_seq": i + 1},
            )
        # 5th CONTROL frame overflows the maxsize=4 queue -> force-close.
        await conn.send_event(
            "session.event.text_delta",
            {"chunk": "overflow", "session_key": "sess-A", "stream_seq": 999},
        )

        assert conn._closing is True
        assert len(calls) == 1

        # No local variable holds the scheduled force-close task; only
        # create_background_task's own retention should keep it alive.
        gc.collect()

        # Unblock the writer so it can be cancelled/awaited, then let the
        # force-close task actually run to completion.
        fake._send_unblock.set()
        await asyncio.wait_for(_wait_for_close(fake), timeout=1.0)
    finally:
        if fake._send_unblock is not None:
            fake._send_unblock.set()
        await conn._stop_writer()

    assert fake.close_code == 1011
    assert fake.close_reason == "writer_backpressure"


async def _wait_for_close(fake: _FakeWebSocket) -> None:
    while fake.close_code is None:
        await asyncio.sleep(0.01)
