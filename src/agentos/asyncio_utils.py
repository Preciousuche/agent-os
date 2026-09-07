"""Small asyncio helpers for test-friendly background task spawning."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

# asyncio.create_task() only holds a *weak* reference to the task it returns
# (see the "Important" note under create_task in the stdlib docs); a task
# nothing else references can be garbage collected mid-execution, silently
# dropping whatever it was doing. Every fire-and-forget task in the codebase
# registers here instead of each call site keeping its own ad-hoc
# self._x_task attribute — one shared, tested place to get this right rather
# than N copies of the same pattern (#1033, same reasoning as #1131's
# BoundedSessionRegistry consolidation).
_background_tasks: set[asyncio.Task[Any]] = set()


def create_background_task(coro: Coroutine[Any, Any, Any], **kwargs: Any) -> Any:
    """Create a background task, retain it until it finishes, and close
    unconsumed coroutines in tests.

    ``**kwargs`` (e.g. ``name=``) are forwarded to ``asyncio.create_task``.
    """
    task = asyncio.create_task(coro, **kwargs)
    frame = getattr(coro, "cr_frame", None)
    if frame is not None and not isinstance(task, asyncio.Task):
        coro.close()
        return task
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
