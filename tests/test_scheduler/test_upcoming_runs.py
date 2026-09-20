"""``upcoming_runs``: the next N fires of a job, for previews (#3101).

It is ``_next_run`` repeated, minus the per-job jitter: a preview describes
the schedule, and jitter is applied when a run is actually placed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from agentos.scheduler.jobs import _next_cron_instant, _next_run, upcoming_runs
from agentos.scheduler.parser import parse_cron
from agentos.scheduler.types import CronJob, ScheduleKind

AFTER = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)


def _job(kind: ScheduleKind, value: str, tz: str = "", **fields: object) -> CronJob:
    return CronJob(id="j", name="j", schedule_kind=kind, cron_expr=value, tz=tz, **fields)


def test_cron_runs_are_the_search_applied_repeatedly() -> None:
    expr = parse_cron("0 9 * * 1-5")
    zone = ZoneInfo("Asia/Shanghai")
    expected = []
    cursor = AFTER
    for _ in range(5):
        cursor = _next_cron_instant(expr, cursor, zone)
        expected.append(cursor)

    assert upcoming_runs(_job(ScheduleKind.CRON, "0 9 * * 1-5", "Asia/Shanghai"), AFTER, 5) == (
        expected
    )


def test_cron_runs_are_strictly_increasing_and_all_in_utc() -> None:
    runs = upcoming_runs(_job(ScheduleKind.CRON, "*/15 * * * *"), AFTER, 6)

    assert len(runs) == 6
    assert all(a < b for a, b in zip(runs, runs[1:], strict=False))
    assert all(run.tzinfo is UTC for run in runs)
    assert runs[0] == AFTER + timedelta(minutes=15)


def test_jitter_is_not_part_of_a_preview() -> None:
    job = _job(ScheduleKind.CRON, "0 9 * * *", jitter_seconds=42.0)

    assert _next_run(job, AFTER) == datetime(2026, 9, 20, 9, 0, 42, tzinfo=UTC)
    assert upcoming_runs(job, AFTER, 1) == [datetime(2026, 9, 20, 9, 0, tzinfo=UTC)]


def test_every_runs_follow_the_anchor_grid() -> None:
    job = _job(ScheduleKind.EVERY, "5400", anchor_at=AFTER)

    assert upcoming_runs(job, AFTER, 3) == [AFTER + timedelta(seconds=5400 * n) for n in (1, 2, 3)]


def test_a_future_one_shot_is_its_single_instant() -> None:
    job = _job(ScheduleKind.AT, "2030-01-01T10:00:00+02:00")

    assert upcoming_runs(job, AFTER, 5) == [datetime(2030, 1, 1, 8, 0, tzinfo=UTC)]


def test_a_past_one_shot_has_no_runs() -> None:
    assert upcoming_runs(_job(ScheduleKind.AT, "2020-01-01T10:00:00+00:00"), AFTER, 5) == []


def test_a_schedule_that_never_fires_yields_nothing_rather_than_raising() -> None:
    assert upcoming_runs(_job(ScheduleKind.CRON, "0 0 31 4 *"), AFTER, 3) == []


def test_a_leap_day_schedule_yields_what_exists_within_the_horizon() -> None:
    runs = upcoming_runs(_job(ScheduleKind.CRON, "0 0 29 2 *"), AFTER, 3)

    assert runs[0] == datetime(2028, 2, 29, tzinfo=UTC)
    assert all((run.month, run.day) == (2, 29) for run in runs)


def test_count_zero_is_empty() -> None:
    assert upcoming_runs(_job(ScheduleKind.CRON, "* * * * *"), AFTER, 0) == []
