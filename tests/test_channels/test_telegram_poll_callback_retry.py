"""Telegram polling must not advance its offset before a callback_query
succeeds (#1027).

Advancing ``_update_offset`` before ``_handle_telegram_callback`` runs, and
swallowing its exception, permanently loses the update on a transient
failure: Telegram never redelivers an update_id once the poller has asked
for anything past it. These tests cover the acceptance criteria from the
issue: bounded retry without advancing past the failed update, later
updates in the same batch held back until it resolves, no reprocessing once
it does resolve, and a bounded give-up so one permanently-failing callback
cannot stall the poll loop forever.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest

from agentos.channels.telegram import TelegramChannel, TelegramChannelConfig


def _channel(**overrides: Any) -> TelegramChannel:
    return TelegramChannel(TelegramChannelConfig(token="test-token", **overrides))


@pytest.mark.asyncio
async def test_handle_polled_callback_retries_before_advancing_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _channel()
    attempts = 0

    async def flaky_handler(cb: dict) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient handler failure")

    monkeypatch.setattr(channel, "_handle_telegram_callback", flaky_handler)

    # First attempt fails: must not acknowledge past the failed update.
    handled = await channel._handle_polled_callback(10, {"id": "cb-1"})
    assert handled is False
    assert channel._update_offset is None
    assert channel._callback_attempts == {10: 1}

    # Retry (the next poll cycle re-delivers the same update_id) succeeds.
    handled = await channel._handle_polled_callback(10, {"id": "cb-1"})
    assert handled is True
    assert channel._update_offset == 11
    assert channel._callback_attempts == {}
    assert attempts == 2


@pytest.mark.asyncio
async def test_handle_polled_callback_gives_up_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _channel()

    async def always_fails(cb: dict) -> None:
        raise RuntimeError("permanent handler failure")

    monkeypatch.setattr(channel, "_handle_telegram_callback", always_fails)

    for expected_attempt in range(1, TelegramChannel.MAX_CALLBACK_ATTEMPTS):
        handled = await channel._handle_polled_callback(20, {"id": "cb-2"})
        assert handled is False
        assert channel._update_offset is None
        assert channel._callback_attempts == {20: expected_attempt}

    # The attempt that reaches the budget gives up instead of retrying
    # again, so a permanently-failing callback cannot stall the loop.
    handled = await channel._handle_polled_callback(20, {"id": "cb-2"})
    assert handled is True
    assert channel._update_offset == 21
    assert channel._callback_attempts == {}


@pytest.mark.asyncio
async def test_handle_polled_callback_does_not_reprocess_resolved_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _channel()
    calls = 0

    async def handler(cb: dict) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(channel, "_handle_telegram_callback", handler)

    assert await channel._handle_polled_callback(30, {"id": "cb-3"}) is True
    assert calls == 1

    # A genuine redelivery of an update_id already resolved (e.g. Telegram
    # resending after we've already advanced past it) must not double-fire
    # the handler's side effects (double-answering the callback query,
    # double-toggling an approval).
    assert await channel._handle_polled_callback(30, {"id": "cb-3"}) is True
    assert calls == 1
    assert channel._update_offset == 31


@pytest.mark.asyncio
async def test_handle_polled_callback_without_int_update_id_is_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No stable id to retry against: fall back to the old best-effort
    behavior (log and move on) rather than crash or stall forever."""
    channel = _channel()

    async def always_fails(cb: dict) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(channel, "_handle_telegram_callback", always_fails)

    handled = await channel._handle_polled_callback(None, {"id": "cb-4"})
    assert handled is True
    assert channel._update_offset is None
    assert channel._callback_attempts == {}


@pytest.mark.asyncio
async def test_poll_loop_holds_back_later_updates_until_failed_one_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _channel(poll_idle_sleep_s=0.01)
    handled_ids: list[str] = []
    failed_once = False

    async def flaky_callback(cb: dict) -> None:
        nonlocal failed_once
        cb_id = cb["id"]
        if cb_id == "cb-fail" and not failed_once:
            failed_once = True
            raise RuntimeError("transient handler failure")
        handled_ids.append(cb_id)

    monkeypatch.setattr(channel, "_handle_telegram_callback", flaky_callback)

    batch = [
        {"update_id": 1, "callback_query": {"id": "cb-fail"}},
        {"update_id": 2, "callback_query": {"id": "cb-later"}},
    ]
    get_updates_calls: list[dict] = []

    async def fake_api(method: str, payload: dict | None = None) -> Any:
        if method == "getUpdates":
            get_updates_calls.append(payload or {})
            # Telegram keeps returning the same batch until our offset
            # moves past update_id=1 -- exactly what "redelivery" means.
            if (payload or {}).get("offset") is None:
                return list(batch)
            return []
        return True

    monkeypatch.setattr(channel, "_api", fake_api)

    task = asyncio.create_task(channel._poll_loop())
    try:
        for _ in range(200):
            await asyncio.sleep(0.01)
            if handled_ids == ["cb-fail", "cb-later"]:
                break
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # Both were eventually handled, cb-fail before cb-later, and only once
    # each -- cb-later was never touched while cb-fail was still pending.
    assert handled_ids == ["cb-fail", "cb-later"]
    assert channel._update_offset == 3
    # At least one getUpdates call happened with no offset yet (the failed
    # attempt), proving the offset had not advanced past update_id=1.
    assert any(call.get("offset") is None for call in get_updates_calls)
