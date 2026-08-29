from __future__ import annotations

from agentos.application.intent_cache import IntentApprovalCache, _extract_rm_targets


def test_extract_rm_targets_compound_commands() -> None:
    # Test single rm
    assert _extract_rm_targets("rm /tmp/a") == ["/tmp/a"]
    assert _extract_rm_targets("rm -rf /tmp/a") == ["/tmp/a"]

    # Test compound commands with separators
    assert _extract_rm_targets("rm /tmp/a; rm -rf /tmp/b") == ["/tmp/a", "/tmp/b"]
    assert _extract_rm_targets("rm /tmp/a && rm -rf /tmp/b") == ["/tmp/a", "/tmp/b"]
    assert _extract_rm_targets("rm /tmp/a || rm -rf /tmp/b") == ["/tmp/a", "/tmp/b"]
    assert _extract_rm_targets("rm /tmp/a | rm -rf /tmp/b") == ["/tmp/a", "/tmp/b"]
    assert _extract_rm_targets("rm /tmp/a & rm -rf /tmp/b") == ["/tmp/a", "/tmp/b"]
    assert _extract_rm_targets("rm /tmp/a\nrm -rf /tmp/b") == ["/tmp/a", "/tmp/b"]

    # Multiple targets in single rm
    assert _extract_rm_targets("rm /tmp/a /tmp/b") == ["/tmp/a", "/tmp/b"]


def test_intent_cache_check_requires_all_approvals() -> None:
    cache = IntentApprovalCache()

    # Record approval for a single target
    cache.record("rm /tmp/approved-target")

    # Simple check should pass
    assert cache.check("rm /tmp/approved-target") is True

    # Compound commands: if they try to run an approved target AND an unapproved
    # one, check() must fail.
    for sep in (";", "&&", "||", "|", "&", "\n"):
        cmd = f"rm /tmp/approved-target{sep}rm -rf /tmp/unapproved-target"
        assert cache.check(cmd) is False, f"Bypass succeeded for separator: {repr(sep)}"
