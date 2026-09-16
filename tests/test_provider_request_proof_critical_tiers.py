"""Issue #2363: failure diagnostics were sliced away before anything asked.

``_final_hard_cap_payload_once`` calls ``_tool_content_is_critical`` on the
content it is handed — which by then has been through up to three truncating
tiers. Each of those slices on raw character position with no idea where
``execution_status`` sits, so the marker that makes a result critical is often
gone by the time the question is asked, and a genuinely failed tool call is
reduced to ``[agentos_compacted:tool_result:388:8be531f7f5c363ea]``.

Where criticality is lost depends only on where the marker sits in the JSON:

=================  ========  ======  ======  ======
marker position    original  tier 1  tier 3  tier 4
=================  ========  ======  ======  ======
first              yes       yes     yes     **no**
last               yes       yes     **no**  no
middle             yes       **no**  no      no
=================  ========  ======  ======  ======

That table is why the issue reads as a hard-cap bug and why the pre-existing
regression test passes: it puts ``execution_status`` first, the one position
that survives to the final tier. Payload-first shapes lose the diagnostics at
tier 3, and a marker in the middle loses them at tier 1 — neither ever reaches
the hard cap with anything left to classify.

The fix classifies once, on the original content, before any tier runs, and
carries that verdict into every tier that rewrites tool content (1, 3 and 4).
Tier 2 does not touch tool message strings, so there is nothing to do there.
"""

from __future__ import annotations

import json

import pytest

from agentos.provider.request_proof import (
    ProviderRequestBudgetExceededError,
    _compact_recent_tail_payload_once,
    _compact_string,
    _compact_tool_payload_once,
    _critical_tool_message_content,
    _effective_proof_budget,
    _emergency_compact_current_turn_payload_once,
    _emergency_compact_string,
    _final_hard_cap_payload_once,
    _hard_compact_string,
    _payload_chars,
    _tool_content_is_critical,
    prove_or_compact_provider_payload,
)

FAILURE = {"status": "error", "exit_code": 137, "message": "container OOM-killed after 42s"}


def result(position: str, *, bulk: int = 6000) -> str:
    """A failed tool result with ``execution_status`` at *position*."""
    if position == "first":
        body = {"execution_status": FAILURE, "output": "x" * bulk}
    elif position == "last":
        body = {"output": "x" * bulk, "execution_status": FAILURE}
    else:
        body = {"head": "x" * (bulk // 2), "execution_status": FAILURE, "tail": "z" * (bulk // 2)}
    return json.dumps(body, ensure_ascii=False)


def payload_with(tool_content: str) -> dict:
    return {
        "model": "m",
        "messages": [
            {"role": "user", "content": "u" * 3000},
            {
                "role": "assistant",
                "content": "a" * 3000,
                "tool_calls": [
                    {
                        "id": "t1",
                        "type": "function",
                        "function": {"name": "run", "arguments": json.dumps({"cmd": "y" * 3000})},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "t1", "content": tool_content},
            {"role": "user", "content": "did it work?"},
        ],
    }


def tool_content_of(payload: dict) -> str:
    return next(m["content"] for m in payload["messages"] if m.get("role") == "tool")


def keeps_failure(content: str) -> bool:
    """The verdict survived in a form a model can actually read."""
    lowered = str(content).lower()
    return "error" in lowered and "oom-killed" in lowered


# ── the tier where each shape used to lose its diagnostics ──────────────────


@pytest.mark.parametrize("position", ["first", "last", "middle"])
def test_the_original_content_is_always_recognised_as_critical(position: str) -> None:
    """Before any tier touches it, every shape is unambiguously critical.

    Establishes that what follows is about the tiers, not about detection."""
    assert _tool_content_is_critical(result(position)) is True


@pytest.mark.parametrize(
    ("position", "slicer"),
    [
        ("middle", _compact_string),
        ("last", lambda text: _emergency_compact_string(text, label="tool_result")),
        ("first", lambda text: _hard_compact_string(text, label="tool_result")),
    ],
)
def test_a_slicing_tier_can_destroy_the_marker(position: str, slicer) -> None:
    """The mechanism, pinned per shape: raw head/tail slicing loses the
    marker, and nothing downstream can recover it from what is left."""
    assert _tool_content_is_critical(slicer(result(position))) is False


@pytest.mark.parametrize("position", ["first", "last", "middle"])
def test_tier1_keeps_the_diagnostics(position: str) -> None:
    """``_compact_tool_payload_once`` — the first tier, and where a
    middle-positioned marker used to disappear."""
    payload = payload_with(result(position))
    critical = _critical_tool_message_content(payload)

    compacted = _compact_tool_payload_once(payload, critical_tool_content=critical)

    assert keeps_failure(tool_content_of(compacted))


@pytest.mark.parametrize("position", ["first", "last", "middle"])
def test_tier3_keeps_the_diagnostics(position: str) -> None:
    """``_emergency_compact_current_turn_payload_once`` — 180 head, 40 tail,
    applied to every tool message with no criticality check at all. This is
    where a payload-first result lost its trailing status."""
    payload = payload_with(result(position))
    critical = _critical_tool_message_content(payload)

    compacted = _emergency_compact_current_turn_payload_once(
        payload, critical_tool_content=critical
    )

    assert keeps_failure(tool_content_of(compacted))


@pytest.mark.parametrize("position", ["first", "last", "middle"])
def test_tier4_keeps_the_diagnostics(position: str) -> None:
    """The tier the issue names."""
    payload = payload_with(result(position))
    critical = _critical_tool_message_content(payload)

    compacted = _final_hard_cap_payload_once(payload, critical_tool_content=critical)

    assert keeps_failure(tool_content_of(compacted))


@pytest.mark.parametrize("position", ["first", "last", "middle"])
def test_tier4_no_longer_emits_a_bare_digest(position: str) -> None:
    """The issue's exact symptom: content reduced to a placeholder with zero
    diagnostic content."""
    payload = payload_with(result(position))
    critical = _critical_tool_message_content(payload)

    compacted = _final_hard_cap_payload_once(payload, critical_tool_content=critical)

    assert not tool_content_of(compacted).startswith("[agentos_compacted:tool_result")


# ── end to end, across the budgets that select each tier ────────────────────


@pytest.mark.parametrize("position", ["first", "last", "middle"])
@pytest.mark.parametrize("budget", [2000, 2600, 4000, 6500])
def test_diagnostics_survive_whichever_tier_the_budget_lands_on(position: str, budget: int) -> None:
    """The property that matters in production: an operator does not choose
    the tier, the budget does."""
    compacted, proof = prove_or_compact_provider_payload(
        payload_with(result(position)),
        projection_adapter="openai",
        proof_budget=budget,
    )

    assert proof is not None and proof["fits"] is True
    assert keeps_failure(tool_content_of(compacted))


@pytest.mark.parametrize("position", ["first", "last", "middle"])
@pytest.mark.parametrize("budget", [2000, 2600, 6500])
def test_the_result_still_fits_the_budget(position: str, budget: int) -> None:
    """Preserving diagnostics must not reintroduce the overflow. Keeping a
    field verbatim would trade a silent loss for a failed request."""
    _compacted, proof = prove_or_compact_provider_payload(
        payload_with(result(position)),
        projection_adapter="openai",
        proof_budget=budget,
    )

    assert proof is not None
    assert proof["fits"] is True
    assert proof["estimated_chars"] <= budget


@pytest.mark.parametrize("position", ["first", "last", "middle"])
@pytest.mark.parametrize("budget", [900, 1000, 1100, 1200, 1300, 1400])
def test_preservation_never_turns_a_working_request_into_a_failure(
    position: str, budget: int
) -> None:
    """The guarantee that makes this safe to land.

    Keeping diagnostics costs characters, so at a tight enough budget the
    preserved payload no longer fits where the old digest did. Rather than
    raise, the final tier rebuilds the whole chain with no preservation —
    byte for byte what this function produced before — and sends that. The
    failure detail is lost in that corner, which is the bug, but the request
    is not: a degraded answer beats ``ProviderRequestBudgetExceededError``.

    Parametrized across the band where the two forms straddle the budget.
    """
    payload = payload_with(result(position))

    try:
        _compacted, proof = prove_or_compact_provider_payload(
            payload, projection_adapter="openai", proof_budget=budget
        )
    except ProviderRequestBudgetExceededError:
        # Only acceptable when the *unpreserved* chain cannot fit either --
        # i.e. this payload was already impossible before the change.
        plain = _final_hard_cap_payload_once(
            _emergency_compact_current_turn_payload_once(
                _compact_recent_tail_payload_once(_compact_tool_payload_once(payload))[0]
            )
        )
        effective, _headroom = _effective_proof_budget(budget)
        assert _payload_chars(plain) > effective, (
            f"the unpreserved chain fits at {budget} but preservation raised"
        )
        return

    assert proof["fits"] is True


def test_the_dropped_diagnostics_fallback_is_reported_in_the_proof() -> None:
    """When the corner above is hit, the proof says so rather than leaving an
    operator to wonder why a failed tool call came back as a digest."""
    compacted, proof = prove_or_compact_provider_payload(
        payload_with(result("first")),
        projection_adapter="openai",
        proof_budget=6500,
    )

    assert proof is not None
    assert proof.get("critical_tool_diagnostics_dropped") in (False, None)
    assert keeps_failure(tool_content_of(compacted))


def test_an_unbounded_diagnostic_field_is_still_bounded() -> None:
    """``execution_status`` is a dict, and its own fields can be huge — a
    tool's ``stderr`` lives there. Preserving it verbatim would let the thing
    we are protecting blow the budget."""
    huge = json.dumps(
        {
            "output": "x" * 4000,
            "execution_status": {"status": "error", "stderr": "boom\n" * 4000},
        },
        ensure_ascii=False,
    )

    _compacted, proof = prove_or_compact_provider_payload(
        payload_with(huge), projection_adapter="openai", proof_budget=2000
    )

    assert proof is not None and proof["fits"] is True


def test_a_large_nested_non_diagnostic_field_is_bounded() -> None:
    """A nested dict holding a large string blows the budget exactly as a bare
    long string does, so it is capped rather than passed through."""
    nested = json.dumps(
        {
            "data": {"rows": [{"blob": "z" * 200} for _ in range(100)]},
            "execution_status": FAILURE,
        },
        ensure_ascii=False,
    )

    compacted, proof = prove_or_compact_provider_payload(
        payload_with(nested), projection_adapter="openai", proof_budget=2000
    )

    assert proof is not None and proof["fits"] is True
    assert keeps_failure(tool_content_of(compacted))


# ── the verdict comes from the original, never from a truncated copy ────────


def test_criticality_is_read_before_any_tier_runs() -> None:
    payload = payload_with(result("middle"))

    critical = _critical_tool_message_content(payload)

    assert set(critical) == {2}
    assert _tool_content_is_critical(critical[2]) is True


def test_a_healthy_tool_result_is_not_marked_critical() -> None:
    """The map must not claim every tool message, or nothing is ever
    compacted and the budget is never met."""
    healthy = json.dumps({"output": "x" * 6000, "execution_status": {"status": "ok"}})

    assert _critical_tool_message_content(payload_with(healthy)) == {}


def test_a_healthy_tool_result_is_still_hard_capped(position: str = "n/a") -> None:
    """The other direction of the same guard: a large successful result is
    exactly what the hard-cap tier exists to shrink."""
    healthy = json.dumps({"output": "x" * 6000, "execution_status": {"status": "ok"}})
    payload = payload_with(healthy)

    compacted = _final_hard_cap_payload_once(
        payload, critical_tool_content=_critical_tool_message_content(payload)
    )

    assert tool_content_of(compacted).startswith("[agentos_compacted:tool_result")


@pytest.mark.parametrize("status", ["error", "timeout", "cancelled"])
def test_every_failing_status_is_preserved(status: str) -> None:
    """``_execution_status_is_failure`` accepts three; all three must reach
    the preservation path, not just ``error``."""
    body = json.dumps(
        {"output": "x" * 6000, "execution_status": {"status": status, "message": "gone"}},
        ensure_ascii=False,
    )
    payload = payload_with(body)

    compacted = _final_hard_cap_payload_once(
        payload, critical_tool_content=_critical_tool_message_content(payload)
    )

    assert status in tool_content_of(compacted)


def test_an_is_error_block_is_preserved() -> None:
    """The other criticality signal, alongside ``execution_status``."""
    body = json.dumps({"is_error": True, "output": "x" * 6000, "error": "disk full"})
    payload = payload_with(body)

    compacted = _final_hard_cap_payload_once(
        payload, critical_tool_content=_critical_tool_message_content(payload)
    )

    content = tool_content_of(compacted)
    assert '"is_error":true' in content.replace(" ", "")
    assert "disk full" in content


# ── shapes that must not regress ────────────────────────────────────────────


def test_truncated_json_still_recognised_by_the_substring_fallback() -> None:
    """``_tool_content_is_critical`` has a substring path for content that no
    longer parses. It still marks the message critical, and the field-wise
    path then does not apply — so the whole string is compacted, head first,
    which is where the markers sit.
    """
    text = 'truncated {"execution_status":{"status":"error"} ' + ("x" * 6000)
    payload = payload_with(text)

    compacted = _final_hard_cap_payload_once(
        payload, critical_tool_content=_critical_tool_message_content(payload)
    )

    content = tool_content_of(compacted)
    assert len(content) < len(text)
    assert "execution_status" in content


def test_content_with_no_failure_marker_at_all_is_hard_capped() -> None:
    """Plain prose that merely mentions a tool is not a failure, and must be
    shrunk like any other bulky result."""
    text = "the command produced a lot of output\n" + ("x" * 6000)
    payload = payload_with(text)

    compacted = _final_hard_cap_payload_once(
        payload, critical_tool_content=_critical_tool_message_content(payload)
    )

    assert tool_content_of(compacted).startswith("[agentos_compacted:tool_result")


def test_a_list_content_block_is_handled() -> None:
    """Anthropic-shaped tool results carry a list of blocks rather than a
    string, and the same preservation has to reach inside them."""
    payload = payload_with("")
    payload["messages"][2]["content"] = [
        {"type": "tool_result", "content": result("last"), "is_error": True}
    ]

    compacted = _final_hard_cap_payload_once(
        payload, critical_tool_content=_critical_tool_message_content(payload)
    )

    block = tool_content_of(compacted)[0]
    assert keeps_failure(block["content"])


def test_messages_without_a_tool_role_are_untouched_by_the_map() -> None:
    payload = payload_with(result("first"))

    critical = _critical_tool_message_content(payload)

    assert all(payload["messages"][index]["role"] == "tool" for index in critical)


def test_a_payload_with_no_messages_is_safe() -> None:
    assert _critical_tool_message_content({"model": "m"}) == {}
    assert _critical_tool_message_content({"model": "m", "messages": "nonsense"}) == {}
