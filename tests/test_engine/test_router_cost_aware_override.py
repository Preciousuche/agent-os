"""Cost-aware tier substitution must run last, not before the decision exists.

The substitution picks the cheapest tier at or above the classified capability.
It has to be the *final* step: the complaint upgrade, the kv-cache
anti-downgrade and the routing-history record all reason about the tier the
classifier actually chose. Applying it up front made the complaint upgrade step
off an already-substituted tier (c1 -> c2 -> c3 on the shipped defaults, i.e. a
far more expensive model on exactly the turns users complain on) and made
``base_tier`` / ``route_class`` report a tier no classifier ever returned.

Default OpenRouter tier prices (USD/M, input + output) put c2 (0.561) below c1
(1.45), so ``_get_cheapest_compatible_tier("c1")`` is ``"c2"`` out of the box —
which is what makes the ordering observable here.
"""

from __future__ import annotations

import pytest

from agentos.engine.pipeline import TurnContext
from agentos.engine.steps import agentos_router as agentos_router_step
from agentos.engine.steps.agentos_router import apply_agentos_router
from agentos.gateway.config import GatewayConfig


@pytest.fixture(autouse=True)
def reset_agentos_router_state(monkeypatch: pytest.MonkeyPatch):
    # Offline pricing only: the cheapest-tier lookup must read the baked-in
    # table, never the live OpenRouter/OpenCAP catalogues.
    monkeypatch.setenv("AGENTOS_OPENROUTER_LIVE_PRICING", "0")
    monkeypatch.setenv("AGENTOS_OPENCAP_LIVE_PRICING", "0")
    agentos_router_step._history_store.clear()
    agentos_router_step._strategy = None
    agentos_router_step._strategy_key = None
    yield
    agentos_router_step._history_store.clear()
    agentos_router_step._strategy = None
    agentos_router_step._strategy_key = None
    monkeypatch.undo()


class _FixedStrategy:
    """History-aware strategy pinned to one tier, so no judge/model is needed."""

    requires_history = True

    def __init__(self, tier: str) -> None:
        self._tier = tier

    async def classify(self, message, valid_tiers, routing_history=None):
        return self._tier, 0.99, "llm_judge", {}


def _pin_strategy(monkeypatch: pytest.MonkeyPatch, tier: str) -> None:
    monkeypatch.setattr(
        agentos_router_step,
        "_get_strategy",
        lambda _config, _llm_cfg=None: _FixedStrategy(tier),
    )


def _make_context(message: str) -> TurnContext:
    config = GatewayConfig()
    config.agentos_router.rollout_phase = "full"
    assert config.agentos_router.cost_aware is True
    return TurnContext(
        message=message,
        session_key="cost-aware-session",
        config=config,
        provider=None,
        model=config.llm.model,
        tool_defs=[],
        system_prompt="system",
        raw_message=None,
        attachments=[],
    )


@pytest.mark.asyncio
async def test_cost_aware_override_does_not_inflate_the_complaint_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_strategy(monkeypatch, "c1")
    ctx = _make_context("that's not right, try again")

    routed = await apply_agentos_router(ctx)

    # The complaint upgrade steps up from the classified c1 -> c2, and the
    # cost-aware pass then keeps c2 (already the cheapest at/above c2).
    # Stepping off a pre-substituted c2 would land on c3 (claude-opus-5).
    assert routed.metadata["routed_tier"] == "c2"

    extra = ctx.metadata["routing_extra"]
    assert extra["complaint_detected"] is True
    assert extra["complaint_upgrade_applied"] is True
    assert extra["base_tier"] == "c1"
    assert extra["route_class"] == "R1"
    assert extra["final_tier"] == routed.metadata["routed_tier"]


@pytest.mark.asyncio
async def test_cost_aware_override_keeps_the_classified_tier_in_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_strategy(monkeypatch, "c1")
    ctx = _make_context("Summarize this paragraph for me.")

    routed = await apply_agentos_router(ctx)

    # c2 is cheaper than c1 on the shipped defaults, so the override fires.
    assert routed.metadata["routed_tier"] == "c2"

    extra = ctx.metadata["routing_extra"]
    # ...but the classification the telemetry reports stays the real one.
    assert extra["base_tier"] == "c1"
    assert extra["route_class"] == "R1"
    assert extra["cost_aware_override_applied"] is True
    assert extra["pre_cost_aware_tier"] == "c1"
    assert extra["final_tier"] == "c2"
    assert extra["final_route_class"] == "R2"
