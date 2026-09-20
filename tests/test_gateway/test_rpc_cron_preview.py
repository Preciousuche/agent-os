"""``cron.preview``: the next fires of a schedule, without creating a job (#3101).

The handler runs the scheduler's own next-run search on the schedule it is
given, so a preview cannot disagree with what ``cron.add`` would schedule.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentos.gateway.rpc import RpcContext
from agentos.gateway.rpc_cron import _handle_cron_preview


def _ctx() -> RpcContext:
    """No scheduler: the preview is pure computation and must not need one."""
    return RpcContext(conn_id="test")


@pytest.mark.asyncio
async def test_a_cron_schedule_with_a_zone_answers_utc_local_and_weekday() -> None:
    result = await _handle_cron_preview(
        {"schedule": {"kind": "cron", "expr": "0 9 * * 1-5", "tz": "Asia/Shanghai"}, "count": 5},
        _ctx(),
    )

    assert result["schedule"] == {"kind": "cron", "value": "0 9 * * 1-5", "tz": "Asia/Shanghai"}
    assert len(result["runs"]) == 5
    for run in result["runs"]:
        assert run["utc"].endswith("T01:00+00:00")
        assert run["local"].endswith("T09:00+08:00")
        assert run["weekday"] in ("Mon", "Tue", "Wed", "Thu", "Fri")
        assert datetime.fromisoformat(run["utc"]) == datetime.fromisoformat(run["local"])


@pytest.mark.asyncio
async def test_runs_are_in_order_and_after_now() -> None:
    before = datetime.now(UTC)

    result = await _handle_cron_preview(
        {"schedule": {"kind": "cron", "expr": "*/5 * * * *"}}, _ctx()
    )

    instants = [datetime.fromisoformat(run["utc"]) for run in result["runs"]]
    assert len(instants) == 5, "the default count"
    assert instants == sorted(instants)
    assert instants[0] > before.replace(second=0, microsecond=0)


@pytest.mark.asyncio
async def test_the_legacy_expression_shim_and_a_top_level_tz_work() -> None:
    result = await _handle_cron_preview(
        {"expression": "30 8 * * *", "tz": "Europe/Berlin", "count": 1}, _ctx()
    )

    assert result["schedule"]["tz"] == "Europe/Berlin"
    assert result["runs"][0]["local"].endswith("T08:30+02:00") or result["runs"][0][
        "local"
    ].endswith("T08:30+01:00")


@pytest.mark.asyncio
async def test_every_and_at_schedules() -> None:
    every = await _handle_cron_preview(
        {"schedule": {"kind": "every", "every_seconds": 5400}, "count": 3}, _ctx()
    )
    at = await _handle_cron_preview(
        {"schedule": {"kind": "at", "at": "2030-01-01T10:00:00+02:00"}}, _ctx()
    )

    instants = [datetime.fromisoformat(run["utc"]) for run in every["runs"]]
    assert [(b - a).total_seconds() for a, b in zip(instants, instants[1:], strict=False)] == [
        5400.0,
        5400.0,
    ]
    assert at["runs"] == [
        {"utc": "2030-01-01T08:00+00:00", "local": "2030-01-01T08:00+00:00", "weekday": "Tue"}
    ]


@pytest.mark.asyncio
async def test_a_schedule_that_never_fires_answers_with_no_runs() -> None:
    result = await _handle_cron_preview(
        {"schedule": {"kind": "cron", "expr": "0 0 31 4 *"}}, _ctx()
    )

    assert result["runs"] == []


@pytest.mark.asyncio
async def test_count_is_validated_and_capped() -> None:
    with pytest.raises(ValueError, match="count"):
        await _handle_cron_preview(
            {"schedule": {"kind": "cron", "expr": "* * * * *"}, "count": 0}, _ctx()
        )
    with pytest.raises(ValueError, match="count"):
        await _handle_cron_preview(
            {"schedule": {"kind": "cron", "expr": "* * * * *"}, "count": True}, _ctx()
        )

    capped = await _handle_cron_preview(
        {"schedule": {"kind": "cron", "expr": "* * * * *"}, "count": 500}, _ctx()
    )

    assert len(capped["runs"]) == 50


@pytest.mark.asyncio
async def test_an_invalid_schedule_is_refused_with_the_parser_reason() -> None:
    with pytest.raises(ValueError, match="out of range"):
        await _handle_cron_preview({"schedule": {"kind": "cron", "expr": "0 25 * * *"}}, _ctx())
    with pytest.raises(ValueError, match="timezone"):
        await _handle_cron_preview(
            {"schedule": {"kind": "cron", "expr": "0 9 * * *", "tz": "Mars/Olympus"}}, _ctx()
        )
    with pytest.raises(ValueError):
        await _handle_cron_preview(None, _ctx())
