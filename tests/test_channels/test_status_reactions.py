"""_BaseStatusReactor: token lifecycle across received/running/failed/completed.

Issue #1560: ``failed()`` only ever appended a new token via ``_add_state``,
the same as ``received()``/``running()``. On a path that rejects a message
before it ever runs (e.g. ``TaskQueueFullError``), ``received()`` fires and
``failed()`` fires, but no ``completed()`` ever follows to pop ``_active`` and
remove the earlier tokens — the outcome emoji (e.g. Slack's ``x``) was left
next to the in-progress one (``white_check_mark``) permanently, and the
``_active[key]`` list leaked for the reactor's lifetime.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentos.channels._reactions import _BaseStatusReactor
from agentos.channels.types import IncomingMessage


class _FakeLogger:
    """Structlog-shaped logger stub: accepts arbitrary kwargs, records nothing."""

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass


class _RecordingReactor(_BaseStatusReactor):
    """A reactor whose ``_add``/``_remove`` just record tokens, no I/O."""

    def __init__(self, *, fail_remove: bool = False, fail_add: bool = False) -> None:
        super().__init__("test", _FakeLogger())
        self.added: list[str] = []
        self.removed: list[str] = []
        self._fail_remove = fail_remove
        self._fail_add = fail_add

    async def _add(self, message: IncomingMessage, state: str) -> str | None:
        if self._fail_add:
            raise RuntimeError("boom")
        token = f"{state}:{message.metadata['ts']}"
        self.added.append(token)
        return token

    async def _remove(self, token: str) -> None:
        if self._fail_remove:
            raise RuntimeError("boom")
        self.removed.append(token)


def _message(ts: str = "123.456") -> IncomingMessage:
    return IncomingMessage(
        sender_id="U1", channel_id="C1", content="hi", metadata={"ts": ts}
    )


@pytest.mark.asyncio
async def test_completed_clears_every_prior_token() -> None:
    reactor = _RecordingReactor()
    msg = _message()

    await reactor.received(msg)
    await reactor.running(msg)
    await reactor.completed(msg)

    assert reactor.removed == ["received:123.456", "running:123.456"]
    assert reactor._active == {}


@pytest.mark.asyncio
async def test_failed_removes_the_in_progress_tokens_and_keeps_its_own() -> None:
    """The received (✅) token is cleared; the failed (❌) token stays and is
    never passed to _remove."""
    reactor = _RecordingReactor()
    msg = _message()

    await reactor.received(msg)
    await reactor.failed(msg)

    assert reactor.added == ["received:123.456", "failed:123.456"]
    assert reactor.removed == ["received:123.456"]
    assert "failed:123.456" not in reactor.removed


@pytest.mark.asyncio
async def test_failed_does_not_leak_the_active_entry_when_no_completed_follows() -> None:
    """Issue #1560: a message rejected before it ever runs gets received()
    then failed() with no completed() to follow. _active must not retain an
    entry for it forever."""
    reactor = _RecordingReactor()
    msg = _message()

    await reactor.received(msg)
    await reactor.failed(msg)

    assert reactor._active == {}
    assert dict(reactor._active) == {}


@pytest.mark.asyncio
async def test_failed_with_no_prior_state_still_adds_and_does_not_leak() -> None:
    """failed() can be the very first call for a message (e.g. a policy
    rejection with no received() at all)."""
    reactor = _RecordingReactor()
    msg = _message()

    await reactor.failed(msg)

    assert reactor.added == ["failed:123.456"]
    assert reactor.removed == []
    assert reactor._active == {}


@pytest.mark.asyncio
async def test_failed_disables_reactor_when_removing_a_stale_token_errors() -> None:
    """A removal failure during the pre-clear disables the reactor, matching
    completed()'s existing behavior, and skips adding the outcome token."""
    reactor = _RecordingReactor(fail_remove=True)
    msg = _message()

    await reactor.received(msg)
    await reactor.failed(msg)

    assert reactor._disabled is True
    assert reactor.added == ["received:123.456"]


@pytest.mark.asyncio
async def test_two_messages_track_independent_active_entries() -> None:
    reactor = _RecordingReactor()
    first = _message("111")
    second = _message("222")

    await reactor.received(first)
    await reactor.received(second)
    await reactor.failed(first)

    assert reactor._active.keys() == {"222"}
    await reactor.completed(second)
    assert reactor._active == {}
