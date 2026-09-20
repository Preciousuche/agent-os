"""Issue #3099: the next-run search stepped one minute at a time.

``_next_run`` found a cron job's next fire by trying every minute for up to
four years, on the gateway's event loop: about a second for a yearly schedule
(1.4 s with a timezone), four for a leap-day one, and four before giving up
on an impossible date -- at every add, after every run, and for every job at
boot. The search now jumps a field at a time. The old scan is kept here as
the oracle: over a grid of schedules, start instants and zones the two must
agree instant for instant, DST edges included.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from agentos.scheduler.jobs import _next_cron_instant, _next_run
from agentos.scheduler.parser import parse_cron
from agentos.scheduler.types import CronJob, ScheduleKind


def _scan(expr: str, after: datetime, tz: ZoneInfo | None, limit_minutes: int) -> datetime | None:
    """The previous implementation, minute by minute, over a bounded window."""
    parsed = parse_cron(expr)
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(limit_minutes):
        wall = candidate.astimezone(tz) if tz is not None else candidate
        if parsed.matches(wall):
            return candidate
        candidate += timedelta(minutes=1)
    return None


def _job(expr: str, tz: str = "", jitter: float = 0.0) -> CronJob:
    return CronJob(
        id="j",
        name="j",
        schedule_kind=ScheduleKind.CRON,
        cron_expr=expr,
        tz=tz,
        jitter_seconds=jitter,
    )


# ── equivalence with the scan ──────────────────────────────────────────────

_EXPRESSIONS = [
    "* * * * *",
    "*/5 * * * *",
    "0 * * * *",
    "30 9 * * *",
    "0 9 * * 1-5",
    "15,45 8-17 * * MON-FRI",
    "0 0 1 * *",
    "0 0 1,15 * 5",  # POSIX either/or: the 1st, the 15th, or any Friday
    "0 0 * * 0",  # Sunday as 0
    "0 0 * * 7",  # Sunday as 7
    "0 12 29 2 *",
    "@hourly",
    "@daily",
    "@weekly",
    "0 22 31 * *",  # the 31st: only some months have one
]
_STARTS = [
    datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    datetime(2026, 2, 28, 23, 59, 30, tzinfo=UTC),
    datetime(2026, 3, 7, 12, 34, 56, tzinfo=UTC),
    datetime(2026, 12, 31, 23, 58, tzinfo=UTC),
    datetime(2028, 2, 28, 12, 0, tzinfo=UTC),  # a leap year
]
_ZONES = [
    None,
    ZoneInfo("America/New_York"),
    ZoneInfo("Asia/Kolkata"),
    ZoneInfo("Pacific/Auckland"),
]
_WINDOW_MINUTES = 60 * 24 * 45  # the scan is slow; 45 days covers every expression above but two


@pytest.mark.parametrize("zone", _ZONES, ids=lambda z: getattr(z, "key", "UTC"))
@pytest.mark.parametrize("after", _STARTS, ids=lambda d: d.strftime("%Y-%m-%dT%H:%M:%S"))
@pytest.mark.parametrize("expr", _EXPRESSIONS)
def test_field_jump_agrees_with_the_minute_scan(
    expr: str, after: datetime, zone: ZoneInfo | None
) -> None:
    expected = _scan(expr, after, zone, _WINDOW_MINUTES)
    if expected is None:
        pytest.skip("next fire is beyond the scan window this test can afford")

    assert _next_cron_instant(parse_cron(expr), after, zone) == expected


@pytest.mark.parametrize(
    ("expr", "after", "expected"),
    [
        ("0 0 29 2 *", datetime(2028, 3, 1, tzinfo=UTC), datetime(2032, 2, 29, tzinfo=UTC)),
        ("0 0 1 1 *", datetime(2026, 1, 2, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
        ("0 0 31 * *", datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 31, tzinfo=UTC)),
    ],
)
def test_sparse_schedules_land_where_the_scan_did(
    expr: str, after: datetime, expected: datetime
) -> None:
    """Too far ahead for the scan to be an affordable oracle; pinned by hand."""
    assert _next_cron_instant(parse_cron(expr), after, None) == expected


# ── daylight saving ────────────────────────────────────────────────────────


def test_a_wall_time_inside_the_spring_forward_gap_is_skipped() -> None:
    """02:30 does not exist on 2026-03-08 in New York; the scan never
    produced it either, because no UTC minute maps onto it."""
    zone = ZoneInfo("America/New_York")
    after = datetime(2026, 3, 8, 6, 0, tzinfo=UTC)  # 01:00 EST that morning

    got = _next_cron_instant(parse_cron("30 2 * * *"), after, zone)

    assert got == _scan("30 2 * * *", after, zone, 60 * 48)
    assert got == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)  # the next day, 02:30 EDT


def test_the_repeated_hour_on_a_fall_back_night_fires_on_its_first_pass() -> None:
    zone = ZoneInfo("America/New_York")
    after = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)  # 00:00 EDT

    got = _next_cron_instant(parse_cron("30 1 * * *"), after, zone)

    assert got == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)  # 01:30 EDT, the first 01:30
    assert got == _scan("30 1 * * *", after, zone, 60 * 3)


def test_the_local_date_not_the_utc_date_decides_the_day_fields() -> None:
    """23:30 in Auckland on a Monday is Sunday 10:30 UTC; the day-of-week rule
    must see Monday."""
    zone = ZoneInfo("Pacific/Auckland")
    after = datetime(2026, 1, 4, 0, 0, tzinfo=UTC)

    got = _next_cron_instant(parse_cron("30 23 * * 1"), after, zone)

    assert got.astimezone(zone).strftime("%a %H:%M") == "Mon 23:30"
    assert got == _scan("30 23 * * 1", after, zone, 60 * 24 * 8)


# ── the contract of _next_run around the search ────────────────────────────


def test_jitter_is_added_to_the_instant() -> None:
    after = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    assert _next_run(_job("0 9 * * *", jitter=42.0), after) == datetime(
        2026, 1, 1, 9, 0, 42, tzinfo=UTC
    )


def test_after_in_a_non_utc_zone_is_handled() -> None:
    after = datetime(2026, 1, 1, 8, 59, tzinfo=ZoneInfo("Europe/Berlin"))  # 07:59 UTC

    assert _next_run(_job("0 9 * * *"), after) == datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def test_a_fire_exactly_at_after_is_not_returned() -> None:
    after = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    assert _next_run(_job("0 9 * * *"), after) == datetime(2026, 1, 2, 9, 0, tzinfo=UTC)


def test_seconds_after_the_minute_do_not_skip_the_next_minute() -> None:
    after = datetime(2026, 1, 1, 8, 59, 30, tzinfo=UTC)

    assert _next_run(_job("0 9 * * *"), after) == datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def test_an_impossible_date_is_refused_with_the_same_message() -> None:
    with pytest.raises(ValueError, match=r"No valid next run found for expression '0 0 31 4 \*'"):
        _next_run(_job("0 0 31 4 *"), datetime(2026, 1, 1, tzinfo=UTC))


def test_a_schedule_beyond_the_horizon_is_refused() -> None:
    """The search gives up where the scan did: four years out."""
    assert (
        _next_cron_instant(parse_cron("0 0 30 2 *"), datetime(2026, 1, 1, tzinfo=UTC), None) is None
    )


# ── the cost ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("expr", "tz"),
    [
        ("0 0 1 1 *", ""),
        ("0 0 1 1 *", "America/New_York"),
        ("0 0 29 2 *", ""),
        ("0 0 29 2 *", "Asia/Shanghai"),
        ("0 0 31 4 *", ""),
    ],
)
def test_sparse_and_impossible_schedules_are_cheap(expr: str, tz: str) -> None:
    """Yearly took ~1 s, leap-day ~4 s, impossible ~4 s on the scan; each must
    now be well under the tick granularity of anything that calls it."""
    after = datetime(2028, 3, 1, tzinfo=UTC)
    started = time.perf_counter()
    try:
        _next_run(_job(expr, tz), after)
    except ValueError:
        pass
    elapsed = time.perf_counter() - started

    assert elapsed < 0.1, f"{expr} took {elapsed:.2f}s"
