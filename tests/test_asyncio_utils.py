"""create_background_task must retain the task it spawns (#1033).

asyncio.create_task() only holds a *weak* reference to the returned task;
with nothing else referencing it, the event loop is free to garbage collect
it mid-execution. create_background_task is the one shared place every
fire-and-forget task in the codebase should register through instead of
each call site keeping (or forgetting to keep) its own reference.
"""

from __future__ import annotations

import asyncio
import gc

import pytest

from agentos.asyncio_utils import _background_tasks, create_background_task


@pytest.mark.asyncio
async def test_create_background_task_survives_with_no_other_reference() -> None:
    started = asyncio.Event()
    finished = asyncio.Event()

    async def work() -> None:
        started.set()
        await asyncio.sleep(0.02)
        finished.set()

    create_background_task(work())
    # No local variable holds the task from here on -- only whatever
    # create_background_task itself retained.
    await started.wait()
    gc.collect()

    await asyncio.wait_for(finished.wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_create_background_task_registers_and_discards_on_completion() -> None:
    async def quick() -> None:
        return None

    task = create_background_task(quick())
    assert task in _background_tasks

    await task
    # add_done_callback fires on a future loop iteration, not synchronously.
    await asyncio.sleep(0)

    assert task not in _background_tasks


@pytest.mark.asyncio
async def test_create_background_task_discards_after_a_raised_exception() -> None:
    async def boom() -> None:
        raise RuntimeError("background task failure")

    task = create_background_task(boom())
    with pytest.raises(RuntimeError, match="background task failure"):
        await task
    await asyncio.sleep(0)

    assert task not in _background_tasks


@pytest.mark.asyncio
async def test_create_background_task_forwards_kwargs() -> None:
    async def quick() -> None:
        return None

    task = create_background_task(quick(), name="my-background-task")
    assert task.get_name() == "my-background-task"
    await task
