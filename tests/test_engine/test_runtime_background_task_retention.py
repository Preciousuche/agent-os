"""_schedule_pre_compaction_flush_status_update must retain its background
task (#1033): it spawned mark_compaction_flush_status_with_retry via a bare
asyncio.create_task(...) with no reference kept, so the retry (up to three
attempts with backoff) could be garbage collected mid-flight, silently
dropping the compaction flush status update.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

import agentos.engine.runtime as runtime_module
from agentos.engine.runtime import TurnRunner


@pytest.mark.asyncio
async def test_schedule_pre_compaction_flush_status_uses_background_task_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    real = runtime_module.create_background_task

    def spy(coro: Any, **kwargs: Any) -> Any:
        calls.append(coro)
        return real(coro, **kwargs)

    monkeypatch.setattr(runtime_module, "create_background_task", spy)

    mark_status_calls: list[tuple[str, str, str]] = []

    async def fake_mark_status(session_key: str, compaction_id: str, status: str) -> bool:
        mark_status_calls.append((session_key, compaction_id, status))
        return True

    runner = TurnRunner.__new__(TurnRunner)
    runner._session_manager = SimpleNamespace(mark_compaction_flush_receipt_status=fake_mark_status)

    runner._schedule_pre_compaction_flush_status_update(
        session_key="sess-1",
        compaction_id="c-1",
        status="pending",
        event_prefix="test.compaction",
    )
    # The call above only schedules the task; let it actually run.
    await asyncio.sleep(0)

    assert len(calls) == 1
    assert mark_status_calls == [("sess-1", "c-1", "pending")]


def test_schedule_pre_compaction_flush_status_no_op_without_session_manager() -> None:
    runner = TurnRunner.__new__(TurnRunner)
    runner._session_manager = None

    # Must not raise even though _session_manager is unset.
    runner._schedule_pre_compaction_flush_status_update(
        session_key="sess-1",
        compaction_id="c-1",
        status="pending",
        event_prefix="test.compaction",
    )
