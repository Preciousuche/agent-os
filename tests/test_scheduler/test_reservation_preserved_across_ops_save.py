"""Issue #1537: update/pause/resume must not clobber a concurrent reservation.

ops.update/.pause/.resume each do get(job_id) -> mutate a field or two ->
save(job), with no lock spanning the read+write pair. If reserve_due_job's
atomic UPDATE claims the job in that gap, a full-column save() from one of
those callers used to overwrite reservation_token/reserved_at/reserved_by/
reservation_source back to the pre-reservation snapshot the caller's get()
captured -- silently reverting a reservation the caller never touched. That
made apply_reserved_result see a reservation_token it no longer recognizes
(discarding the execution result) and left the row looking unreserved (so
the next tick could reserve and run the same job again, concurrently with
the run still in flight).

The fix: update/pause/resume now go through
JobStore.save_preserving_reservation, which writes every column except the
reservation quartet, so a concurrent reservation's columns are left exactly
as reserve_due_job wrote them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agentos.scheduler.jobs import apply_reserved_result
from agentos.scheduler.ops import SchedulerOps
from agentos.scheduler.payloads import make_agent_turn_payload
from agentos.scheduler.persistence import JobStore
from agentos.scheduler.types import (
    JobExecution,
    JobReservation,
    JobStatus,
    ScheduleKind,
    SessionTarget,
)


async def _open_ops(tmp_path: Path) -> tuple[JobStore, SchedulerOps]:
    store = JobStore(str(tmp_path / "cron.db"))
    await store.open()
    return store, SchedulerOps(store)


async def _add_due_job(ops: SchedulerOps, name: str = "demo") -> str:
    job = await ops.add(
        name=name,
        handler_key="agent_run",
        payload=make_agent_turn_payload("ping"),
        session_target=SessionTarget.ISOLATED,
        schedule_kind=ScheduleKind.EVERY,
        schedule_value="60",
    )
    # Force it due right now rather than 60s out.
    job.next_run_at = datetime.now(UTC)
    await ops._store.save(job)
    return job.id


async def test_pause_racing_a_reservation_does_not_revert_it(tmp_path: Path) -> None:
    """The exact reproduction: Task A reads the job for pause() while Task B's
    atomic reserve_due_job lands in the gap before A's save()."""
    store, ops = await _open_ops(tmp_path)
    try:
        job_id = await _add_due_job(ops)

        # Task A: read the job the way ops.pause() does, before its save().
        job = await store.get(job_id)
        assert job is not None

        # Task B: an unrelated atomic reservation lands in the gap.
        now = datetime.now(UTC)
        reservation = await store.reserve_due_job(job_id, now)
        assert isinstance(reservation, JobReservation)

        # Task A finishes: ops.pause() mutates status and saves.
        job.status = JobStatus.PAUSED
        job.updated_at = now
        await store.save_preserving_reservation(job)

        after = await store.get(job_id)
        assert after is not None
        assert after.status == JobStatus.PAUSED
        assert after.reservation_token == reservation.token
        assert after.reserved_by == reservation.reserved_by
        assert after.reservation_source == reservation.reservation_source
        assert after.reserved_at is not None
    finally:
        await store.close()


async def test_resume_racing_a_reservation_does_not_revert_it(tmp_path: Path) -> None:
    """reserve_due_job only claims a PENDING job, so the realistic race is a
    (redundant) resume() on a job that is already PENDING, landing against a
    concurrent reservation of that same job — not a resume of a job that is
    still PAUSED in the database, which reserve_due_job would refuse anyway."""
    store, ops = await _open_ops(tmp_path)
    try:
        job_id = await _add_due_job(ops)

        job = await store.get(job_id)
        assert job is not None
        assert job.status == JobStatus.PENDING

        now = datetime.now(UTC)
        reservation = await store.reserve_due_job(job_id, now)
        assert isinstance(reservation, JobReservation)

        # ops.resume()'s own mutation, applied to the pre-reservation snapshot.
        job.status = JobStatus.PENDING
        job.updated_at = now
        await store.save_preserving_reservation(job)

        after = await store.get(job_id)
        assert after is not None
        assert after.reservation_token == reservation.token
    finally:
        await store.close()


async def test_update_racing_a_reservation_does_not_revert_it(tmp_path: Path) -> None:
    store, ops = await _open_ops(tmp_path)
    try:
        job_id = await _add_due_job(ops)

        job = await store.get(job_id)
        assert job is not None

        now = datetime.now(UTC)
        reservation = await store.reserve_due_job(job_id, now)
        assert isinstance(reservation, JobReservation)

        job.name = "renamed-mid-flight"
        job.updated_at = now
        await store.save_preserving_reservation(job)

        after = await store.get(job_id)
        assert after is not None
        assert after.name == "renamed-mid-flight"
        assert after.reservation_token == reservation.token
    finally:
        await store.close()


async def test_execution_result_is_not_dropped_after_a_racing_pause(tmp_path: Path) -> None:
    """End-to-end: the in-flight run's result must still apply after a
    concurrent pause() that raced its reservation, instead of being silently
    discarded by apply_reserved_result's token mismatch check."""
    store, ops = await _open_ops(tmp_path)
    try:
        job_id = await _add_due_job(ops)
        now = datetime.now(UTC)
        reservation = await store.reserve_due_job(job_id, now)
        assert isinstance(reservation, JobReservation)

        # An unrelated pause() call races the in-flight run.
        await ops.pause(job_id)

        # The run started under `reservation` finishes and reports its result.
        execution = JobExecution(
            id="run-1",
            job_id=job_id,
            started_at=now,
            finished_at=datetime.now(UTC),
            success=True,
        )
        applied = await apply_reserved_result(job_id, reservation.token, execution, store)

        assert applied is True
        after = await store.get(job_id)
        assert after is not None
        # apply_reserved_result's own PAUSED handling clears the reservation
        # once it can see the token it expects, rather than dropping the
        # result because the token had already been wiped out from under it.
        assert after.reservation_token == ""
        assert after.status == JobStatus.PAUSED
    finally:
        await store.close()


async def test_a_second_reservation_is_still_refused_after_a_racing_pause(
    tmp_path: Path,
) -> None:
    """The job must stay reserved (busy) from the scheduler's perspective —
    a racing pause() must not un-reserve it and let a second tick claim it
    while the first run is still in flight."""
    store, ops = await _open_ops(tmp_path)
    try:
        job_id = await _add_due_job(ops)
        now = datetime.now(UTC)
        first = await store.reserve_due_job(job_id, now)
        assert isinstance(first, JobReservation)

        await ops.pause(job_id)

        second = await store.reserve_due_job(job_id, now)
        assert not isinstance(second, JobReservation)
    finally:
        await store.close()


async def test_release_reservation_still_writes_the_reservation_columns(
    tmp_path: Path,
) -> None:
    """The reservation protocol's own writers (release_reservation) must be
    unaffected -- they go through save(), not save_preserving_reservation."""
    store, ops = await _open_ops(tmp_path)
    try:
        job_id = await _add_due_job(ops)
        now = datetime.now(UTC)
        reservation = await store.reserve_due_job(job_id, now)
        assert isinstance(reservation, JobReservation)

        released = await store.release_reservation(job_id, reservation.token)

        assert released is True
        after = await store.get(job_id)
        assert after is not None
        assert after.reservation_token == ""
    finally:
        await store.close()
