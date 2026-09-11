"""Regression tests for build_policy's require_approval gating (#1795)."""

from __future__ import annotations

from pathlib import Path

from agentos.sandbox.config import SandboxSettings
from agentos.sandbox.policy import LevelHints, build_policy, select_level
from agentos.sandbox.types import SecurityLevel


def test_trusted_write_outside_workspace_still_requires_approval(tmp_path: Path) -> None:
    """A trusted-source fs.write escalated to STRICT for leaving the
    workspace must still require approval -- that's the exact risk STRICT
    exists to gate here, independent of the request's trust."""
    hints = LevelHints(trusted_source=True, writes_outside_workspace=True)
    level = select_level("fs.write", hints)
    assert level is SecurityLevel.STRICT

    policy = build_policy(
        level,
        "fs.write",
        tmp_path,
        SandboxSettings(sandbox=True, security_grading=True),
        trusted=hints.trusted_source,
        hints=hints,
    )

    assert policy.require_approval is True


def test_trusted_action_crossing_trust_boundary_still_requires_approval(tmp_path: Path) -> None:
    hints = LevelHints(trusted_source=True, crosses_trust_boundary=True)
    level = select_level("git.write", hints)
    assert level is SecurityLevel.STRICT

    policy = build_policy(
        level,
        "git.write",
        tmp_path,
        SandboxSettings(sandbox=True, security_grading=True),
        trusted=hints.trusted_source,
        hints=hints,
    )

    assert policy.require_approval is True


def test_untrusted_source_at_strict_still_requires_approval_without_hints(tmp_path: Path) -> None:
    """Existing behavior (no hints passed) must be unaffected by the fix."""
    policy = build_policy(
        SecurityLevel.STRICT,
        "network.fetch",
        tmp_path,
        SandboxSettings(sandbox=True, security_grading=True),
        trusted=False,
    )

    assert policy.require_approval is True


def test_trusted_standard_action_does_not_require_approval(tmp_path: Path) -> None:
    """Existing behavior for the common case must be unaffected."""
    policy = build_policy(
        SecurityLevel.STANDARD,
        "fs.write",
        tmp_path,
        SandboxSettings(sandbox=True, security_grading=True),
        trusted=True,
    )

    assert policy.require_approval is False
