"""``agentos cron preview``: the next fires of a schedule, before creating a job (#3101).

The command sends the same schedule shape as ``cron add`` to ``cron.preview``
and renders the answer; the search itself lives in the scheduler behind the
gateway, so the CLI stays an RPC client like every other ``cron`` command.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from typer.testing import CliRunner

from agentos.cli import cron_cmd
from agentos.cli.main import app

runner = CliRunner()

_SHANGHAI_RUNS = [
    {"utc": "2026-09-21T01:00+00:00", "local": "2026-09-21T09:00+08:00", "weekday": "Mon"},
    {"utc": "2026-09-22T01:00+00:00", "local": "2026-09-22T09:00+08:00", "weekday": "Tue"},
]


class _StubClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.response = response

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, params))
        return self.response


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch):
    """Answer ``cron.preview`` with whatever the test installs as ``response``."""
    client = _StubClient({"schedule": {"kind": "cron", "value": "", "tz": ""}, "runs": []})

    def _runner(fn, *, json_output: bool = False):  # noqa: ARG001
        return asyncio.run(fn(client))

    monkeypatch.setattr(cron_cmd, "run_gateway_sync", _runner)
    return client


def _preview(*args: str):
    return runner.invoke(app, ["cron", "preview", *args])


# ── what is asked of the gateway ───────────────────────────────────────────


def test_a_cron_schedule_is_sent_the_way_cron_add_sends_it(gateway: _StubClient) -> None:
    gateway.response = {
        "schedule": {"kind": "cron", "value": "0 9 * * 1-5", "tz": "Asia/Shanghai"},
        "runs": _SHANGHAI_RUNS,
    }

    result = _preview("--cron", "0 9 * * 1-5", "--tz", "Asia/Shanghai", "-n", "2")

    assert result.exit_code == 0, result.output
    assert gateway.calls == [
        (
            "cron.preview",
            {
                "schedule": {"kind": "cron", "expr": "0 9 * * 1-5", "tz": "Asia/Shanghai"},
                "count": 2,
            },
        )
    ]


def test_the_legacy_expression_flag_sends_the_shim_shape(gateway: _StubClient) -> None:
    _preview("--expression", "0 12 * * *", "--tz", "Europe/Berlin")

    assert gateway.calls == [
        ("cron.preview", {"expression": "0 12 * * *", "tz": "Europe/Berlin", "count": 5})
    ]


def test_every_and_at_send_their_structured_shapes(gateway: _StubClient) -> None:
    _preview("--every", "90m", "-n", "3")
    _preview("--at", "2030-01-01T10:00:00+02:00")

    assert gateway.calls == [
        ("cron.preview", {"schedule": {"kind": "every", "every_seconds": 5400}, "count": 3}),
        (
            "cron.preview",
            {"schedule": {"kind": "at", "at": "2030-01-01T10:00:00+02:00"}, "count": 5},
        ),
    ]


# ── how the answer is shown ────────────────────────────────────────────────


def test_a_zoned_schedule_prints_utc_weekday_and_local(gateway: _StubClient) -> None:
    gateway.response = {
        "schedule": {"kind": "cron", "value": "0 9 * * 1-5", "tz": "Asia/Shanghai"},
        "runs": _SHANGHAI_RUNS,
    }

    result = _preview("--cron", "0 9 * * 1-5", "--tz", "Asia/Shanghai", "-n", "2")

    assert "Next 2 run(s) for cron 0 9 * * 1-5 (Asia/Shanghai):" in result.output
    assert "2026-09-21T01:00+00:00 UTC  (Mon)   2026-09-21T09:00+08:00" in result.output
    assert "2026-09-22T01:00+00:00 UTC  (Tue)   2026-09-22T09:00+08:00" in result.output


def test_an_unzoned_schedule_prints_no_local_column(gateway: _StubClient) -> None:
    gateway.response = {
        "schedule": {"kind": "every", "value": "5400", "tz": ""},
        "runs": [
            {"utc": "2026-09-20T09:00+00:00", "local": "2026-09-20T09:00+00:00", "weekday": "Sun"}
        ],
    }

    result = _preview("--every", "90m", "-n", "1")

    assert "Next 1 run(s) for every 5400:" in result.output
    assert "2026-09-20T09:00+00:00 UTC  (Sun)" in result.output
    assert result.output.count("2026-09-20T09:00") == 1


def test_json_passes_the_gateway_answer_through(gateway: _StubClient) -> None:
    gateway.response = {
        "schedule": {"kind": "cron", "value": "0 9 * * 1-5", "tz": "Asia/Shanghai"},
        "runs": _SHANGHAI_RUNS,
    }

    result = _preview("--cron", "0 9 * * 1-5", "--tz", "Asia/Shanghai", "--json")

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == gateway.response


def test_a_schedule_that_never_fires_is_said_so(gateway: _StubClient) -> None:
    gateway.response = {"schedule": {"kind": "cron", "value": "0 0 31 4 *", "tz": ""}, "runs": []}

    result = _preview("--cron", "0 0 31 4 *")

    assert result.exit_code == 2
    assert "`0 0 31 4 *` never fires" in result.output


# ── refused before any request ─────────────────────────────────────────────


def test_exactly_one_schedule_source_is_required(gateway: _StubClient) -> None:
    none = _preview("-n", "3")
    two = _preview("--cron", "0 9 * * *", "--every", "5m")

    assert none.exit_code != 0 and two.exit_code != 0
    assert "exactly one schedule source" in none.output + two.output
    assert gateway.calls == []


def test_count_must_be_positive(gateway: _StubClient) -> None:
    result = _preview("--cron", "0 9 * * *", "-n", "0")

    assert result.exit_code != 0
    assert "at least 1" in result.output
    assert gateway.calls == []
