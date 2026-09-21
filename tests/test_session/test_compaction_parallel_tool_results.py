"""Issue #3077: compaction split a parallel tool call from its results.

``_find_turn_boundary_cut`` stepped the cut back only when the last removed
entry was the assistant tool call *and* the first kept entry was its result.
With parallel calls the transcript is ``assistant(tool_calls) → result_1 →
result_2``; a cut landing between the results saw a tool result on both sides,
matched neither half of that pair test, and kept a history that opened with
``result_2`` -- which every provider rejects ("an assistant message with
tool_calls must be followed by tool messages responding to each id").

The condition is now on the kept side alone: while the first kept entry is a
tool result, step back. That reaches the assistant call for one result or
many, and for the Agent's flattened ``[Tool result …]`` form too.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentos.session.compaction import (
    CompactionConfig,
    CompactionRequest,
    _entry_tokens,
    _find_turn_boundary_cut,
    _is_tool_result_entry,
    compact_context_new,
)


def _parallel_turn(fan_out: int, *, first_result_words: int = 50) -> list[dict[str, Any]]:
    """user → assistant with *fan_out* calls → that many results → assistant."""
    calls = [{"id": f"call_{i}", "function": {"name": "read_file"}} for i in range(fan_out)]
    results: list[dict[str, Any]] = [
        {
            "role": "tool",
            "tool_call_id": f"call_{i}",
            "content": f"file {i} data " * (first_result_words if i == 0 else 1),
        }
        for i in range(fan_out)
    ]
    return [
        {"role": "user", "content": "analyze files"},
        {"role": "assistant", "content": "", "tool_calls": calls},
        *results,
        {"role": "assistant", "content": "Analysis complete."},
    ]


def _opens_cleanly(entries: list[dict[str, Any]], cut: int) -> bool:
    return cut >= len(entries) or not _is_tool_result_entry(entries[cut])


# ── the report ──────────────────────────────────────────────────────────────


def test_the_issues_exact_reproduction() -> None:
    entries = _parallel_turn(2)

    cut = _find_turn_boundary_cut(entries, keep_budget=30)

    assert cut == 1, "the cut must land on the assistant call, not between its results"
    assert entries[cut]["role"] == "assistant"
    assert [c["id"] for c in entries[cut]["tool_calls"]] == ["call_0", "call_1"]


@pytest.mark.parametrize("fan_out", [2, 3, 5, 8])
def test_a_cut_between_parallel_results_steps_back_to_the_call(fan_out: int) -> None:
    """Whatever the fan-out, and wherever between the results the budget cut
    lands, the kept slice starts at the assistant call."""
    entries = _parallel_turn(fan_out)
    for budget in range(1, 200):
        cut = _find_turn_boundary_cut(entries, keep_budget=budget)

        assert _opens_cleanly(entries, cut), f"budget={budget}: kept opens with {entries[cut]}"
        if 0 < cut < len(entries):
            assert entries[cut]["role"] != "tool"


def test_the_kept_slice_never_opens_with_a_tool_result_across_a_long_session() -> None:
    """Several parallel turns of different widths, every budget from 1 to the
    session's full size: the property the provider contract needs."""
    entries: list[dict[str, Any]] = []
    for fan_out in (1, 3, 2, 4):
        entries.extend(_parallel_turn(fan_out, first_result_words=5))

    for budget in range(1, 400):
        cut = _find_turn_boundary_cut(entries, keep_budget=budget)

        assert _opens_cleanly(entries, cut), f"budget={budget}"


def test_the_agents_flattened_form_is_handled_the_same_way() -> None:
    """The Agent records tool use as text: an assistant ``[Used tool: …]`` then
    one ``[Tool result …]`` user entry per call. The same kept-side rule
    covers it."""
    entries = [
        {"role": "user", "content": "old context " * 20},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "[Used tool: read_file] [Used tool: read_file]"},
        {"role": "user", "content": "[Tool result (toolu_1): first " * 10},
        {"role": "user", "content": "[Tool result (toolu_2): second]"},
        {"role": "assistant", "content": "answer"},
    ]

    for budget in range(1, 120):
        cut = _find_turn_boundary_cut(entries, keep_budget=budget)

        assert not str(entries[cut]["content"]).startswith("[Tool result "), f"budget={budget}"


# ── through the public entry point ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_compaction_keeps_a_parallel_turn_whole() -> None:
    entries = [
        {"role": "user", "content": "old context", "token_count": 10},
        {"role": "user", "content": "analyze", "token_count": 4},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1"}, {"id": "call_2"}],
            "token_count": 4,
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "first", "token_count": 12},
        {"role": "tool", "tool_call_id": "call_2", "content": "second", "token_count": 3},
        {"role": "assistant", "content": "done", "token_count": 3},
    ]
    request = CompactionRequest(
        session_id="parallel-tool-results",
        entries=entries,
        context_window_tokens=30,
        config=CompactionConfig(safety_margin=1.0),
    )

    result = await compact_context_new(request)

    assert result.removed_count > 0
    kept = result.kept_entries
    assert kept[0]["role"] == "assistant"
    assert [c["id"] for c in kept[0]["tool_calls"]] == ["call_1", "call_2"]
    assert [e.get("tool_call_id") for e in kept[1:3]] == ["call_1", "call_2"]


@pytest.mark.asyncio
async def test_compaction_skips_when_the_parallel_turn_is_the_whole_history() -> None:
    """The existing escape hatch: if stepping back reaches index 0, do not
    compact rather than orphan tool state."""
    entries = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1"}, {"id": "call_2"}],
            "token_count": 4,
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "first", "token_count": 10},
        {"role": "tool", "tool_call_id": "call_2", "content": "second", "token_count": 4},
        {"role": "user", "content": "q2", "token_count": 3},
        {"role": "assistant", "content": "answer", "token_count": 3},
    ]
    request = CompactionRequest(
        session_id="parallel-whole-history",
        entries=entries,
        context_window_tokens=26,
        config=CompactionConfig(safety_margin=1.0),
    )

    result = await compact_context_new(request)

    assert result.removed_count == 0
    assert result.skip_reason == "no_safe_turn_boundary"
    assert result.kept_entries == entries


# ── what must not change ────────────────────────────────────────────────────


def test_a_single_call_pair_is_still_kept_together() -> None:
    entries = _parallel_turn(1)

    for budget in range(1, 200):
        cut = _find_turn_boundary_cut(entries, keep_budget=budget)

        assert _opens_cleanly(entries, cut)


def test_a_clean_boundary_is_not_moved() -> None:
    """A budget cut that already lands on a user turn stays put: the fix only
    steps back past tool results, never past ordinary messages."""
    entries = [
        {"role": "user", "content": "a " * 30},
        {"role": "assistant", "content": "b " * 30},
        {"role": "user", "content": "c"},
        {"role": "assistant", "content": "d"},
    ]
    budget = sum(len(str(e["content"])) // 4 + 1 for e in entries[2:]) + 2

    cut = _find_turn_boundary_cut(entries, keep_budget=budget)

    assert cut == 2


def test_a_call_with_no_result_yet_is_a_clean_boundary() -> None:
    """A trailing assistant call whose results have not arrived orphans
    nothing: the cut may land on it and stays there."""
    entries = [
        {"role": "user", "content": "old " * 40},
        {"role": "assistant", "content": "older answer " * 10},
        {"role": "user", "content": "now read both"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_0"}, {"id": "call_1"}]},
    ]
    budget = _entry_tokens(entries[3]) + _entry_tokens(entries[2])

    cut = _find_turn_boundary_cut(entries, keep_budget=budget)

    assert cut == 2
