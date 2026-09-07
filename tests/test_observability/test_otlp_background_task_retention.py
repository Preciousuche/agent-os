"""OtlpTraceSink.write()'s immediate flush must retain its background task
(#1033, folded in from #1047): it spawned self.flush() via a bare
loop.create_task(...) with no reference kept, so the event loop was free to
garbage collect it mid-export, silently dropping a batch of trace events.
"""

from __future__ import annotations

import asyncio
import gc
from typing import Any

import pytest

import agentos.observability.otlp as otlp_module
from agentos.observability.otlp import OtlpTraceSink
from agentos.observability.trace import TraceContext, TraceEvent


def _event(i: int) -> TraceEvent:
    ctx = TraceContext.new(
        trace_id=f"trace-{i}" * 4,
        session_key="sess-test",
        turn_id="turn-1",
        run_id="run-1",
        parent_run_id="parent-1",
        agent_id="main",
    )
    return TraceEvent(kind="llm_call", context=ctx, attrs={"i": i})


@pytest.mark.asyncio
async def test_write_immediate_flush_uses_background_task_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    real = otlp_module.create_background_task

    def spy(coro: Any, **kwargs: Any) -> Any:
        calls.append(coro)
        return real(coro, **kwargs)

    monkeypatch.setattr(otlp_module, "create_background_task", spy)

    sink = OtlpTraceSink(
        endpoint="http://localhost:4318",
        service_name="agentos-test",
        service_version="1.0.0",
        batch_size=1,
        flush_interval_s=0,  # disable the periodic loop; only the
        # immediate should_flush path under test should run.
    )

    flushed = asyncio.Event()

    async def fake_flush() -> None:
        flushed.set()

    monkeypatch.setattr(sink, "flush", fake_flush)

    sink.write(_event(1))
    assert len(calls) == 1

    # No local variable holds the scheduled flush task; only
    # create_background_task's own retention should keep it alive.
    gc.collect()

    await asyncio.wait_for(flushed.wait(), timeout=1.0)
