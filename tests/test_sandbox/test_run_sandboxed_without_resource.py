"""``run_sandboxed`` must still run the command when :mod:`resource` is absent.

``resource`` is POSIX-only. Its absence means "rlimits cannot be applied",
not "the command cannot run" — the wall-clock timeout is cross-platform and
must keep working. These tests monkeypatch the feature flag rather than
gating on ``sys.platform`` so they are meaningful on every CI runner.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from agentos.safety import sandbox as sandbox_mod
from agentos.safety.sandbox import (
    REASON_OK,
    REASON_WALL_LIMIT,
    SandboxLimits,
    run_sandboxed,
)
from agentos.sandbox.backend.noop import NoopBackend
from agentos.sandbox.types import (
    MountSpec,
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)


@pytest.fixture
def without_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a host where ``import resource`` failed (e.g. Windows)."""
    monkeypatch.setattr(sandbox_mod, "HAS_RESOURCE", False)
    monkeypatch.setattr(sandbox_mod, "_resource", None)


def _policy(workspace: Path) -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(MountSpec(host_path=workspace, sandbox_path=Path("/workspace"), mode="rw"),),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(),
        env_allowlist=("PATH",),
        require_approval=False,
    )


def test_child_still_runs_without_resource_module(without_resource: None) -> None:
    result = run_sandboxed([sys.executable, "-c", "print('ok')"])

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
    assert result.reason == REASON_OK


def test_wall_limit_still_fires_without_resource_module(without_resource: None) -> None:
    result = run_sandboxed(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        SandboxLimits(wall_seconds=1),
    )

    assert result.reason == REASON_WALL_LIMIT
    assert result.returncode != 0


def test_missing_rlimits_are_reported_on_the_result(without_resource: None) -> None:
    result = run_sandboxed([sys.executable, "-c", "print('ok')"])

    assert sandbox_mod.NOTE_NO_RLIMITS in result.notes


def test_rlimits_are_applied_note_absent_when_resource_is_available() -> None:
    if not sandbox_mod.HAS_RESOURCE:  # pragma: no cover — Windows CI only
        pytest.skip("host has no resource module")

    result = run_sandboxed([sys.executable, "-c", "print('ok')"])

    assert result.notes == ()


@pytest.mark.asyncio
async def test_noop_backend_surfaces_the_degradation(
    without_resource: None,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = SandboxRequest(
        argv=(sys.executable, "-c", "print('ok')"),
        cwd=tmp_path,
        action_kind="code.exec",
        policy=_policy(tmp_path),
    )

    with caplog.at_level(logging.WARNING, logger="agentos.sandbox.backend.noop"):
        result = await NoopBackend().run(request)

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
    assert any("sandbox.rlimits_unavailable" in rec.message for rec in caplog.records)
