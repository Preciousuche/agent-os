"""`agentos upgrade` command — delegate, check, dry-run, restart+verify."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from agentos.cli import upgrade_cmd
from agentos.cli.install_method import InstallMethod, UpgradePlan

runner = CliRunner()

# A fake checkout root. Assert against SOURCE_DIR_TEXT, never the literal, so the
# expectation matches what the command actually prints: Path renders this as
# "\w\agent-os" on Windows and "/w/agent-os" elsewhere.
SOURCE_DIR = Path("/w/agent-os")
SOURCE_DIR_TEXT = str(SOURCE_DIR)


@pytest.fixture(autouse=True)
def _no_source_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quarantine the PEP 610 probe from the developer's own machine.

    A maintainer's checkout really is installed from a directory, so without
    this the source-install notice would fire in every test and its text would
    embed a machine-dependent path. Tests that want the notice opt in.
    """

    monkeypatch.setattr(upgrade_cmd, "installed_from_directory", lambda *a, **k: None)


def _app() -> typer.Typer:
    app = typer.Typer()
    app.command("upgrade")(upgrade_cmd.upgrade_command)

    @app.command("noop")
    def _noop() -> None:  # keeps Typer in multi-command mode
        return None

    return app


def _delegated_plan() -> UpgradePlan:
    return UpgradePlan(
        method=InstallMethod.UV_TOOL,
        delegated=True,
        tool="/abs/uv",
        command=[
            "/abs/uv",
            "tool",
            "install",
            "--force",
            "--python",
            "3.12",
            "use-agent-os[recommended]",
        ],
        manual_hint='uv tool install --force --python 3.12 "use-agent-os[recommended]"',
    )


def _pip_plan() -> UpgradePlan:
    return UpgradePlan(
        method=InstallMethod.PIP,
        delegated=False,
        tool=None,
        command=["python", "-m", "pip", "install", "--upgrade", "use-agent-os"],
        manual_hint="python -m pip install --upgrade use-agent-os",
    )


def _ok_run(*_: Any, **__: Any) -> upgrade_cmd.UpgradeRunResult:
    return upgrade_cmd.UpgradeRunResult(
        ok=True, timed_out=False, returncode=0, stdout="upgraded", stderr=""
    )


def _json_payload(stdout: str) -> dict[str, Any]:
    """The `--json` object, which progress prose may precede on stdout."""

    start = stdout.index("{")
    payload = json.loads(stdout[start:])
    assert isinstance(payload, dict)
    return payload


# --- --check ---------------------------------------------------------------


def test_check_reports_newer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(
        "agentos.compat.pypi_client.latest_version", lambda timeout=5.0: "99999.1.1"
    )
    result = runner.invoke(_app(), ["upgrade", "--check"])
    assert result.exit_code == 0
    assert "newer version is available" in result.stdout


def test_check_offline_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr("agentos.compat.pypi_client.latest_version", lambda timeout=5.0: None)
    result = runner.invoke(_app(), ["upgrade", "--check"])
    assert result.exit_code == 0
    assert "could not check (offline)" in result.stdout


def test_check_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"run": False}
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(
        "agentos.compat.pypi_client.latest_version", lambda timeout=5.0: "99999.1.1"
    )
    monkeypatch.setattr(
        upgrade_cmd,
        "_run_upgrade_subprocess",
        lambda *a, **k: called.__setitem__("run", True),
    )
    runner.invoke(_app(), ["upgrade", "--check"])
    assert called["run"] is False


# --- non-delegated (pip/editable) ------------------------------------------


def test_pip_prints_manual_and_exits_3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _pip_plan)
    result = runner.invoke(_app(), ["upgrade"])
    assert result.exit_code == 3
    assert "pip install --upgrade use-agent-os" in result.stdout


# --- --dry-run -------------------------------------------------------------


def test_dry_run_touches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = {"run": False}
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(
        upgrade_cmd, "_run_upgrade_subprocess", lambda *a, **k: ran.__setitem__("run", True)
    )
    result = runner.invoke(_app(), ["upgrade", "--dry-run"])
    assert result.exit_code == 0
    assert (
        "Would run: /abs/uv tool install --force --python 3.12 use-agent-os[recommended]"
        in result.stdout
    )
    assert ran["run"] is False


# --- source-install notice (PEP 610 directory install) ---------------------


def test_source_install_notice_names_the_way_back(monkeypatch: pytest.MonkeyPatch) -> None:
    # A checkout-backed install is exactly the case this command replaces, so
    # it must say so and name install_source.sh — but never block.
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(upgrade_cmd, "installed_from_directory", lambda *a, **k: SOURCE_DIR)
    monkeypatch.setattr(upgrade_cmd, "_run_upgrade_subprocess", _ok_run)
    monkeypatch.setattr(upgrade_cmd, "_installed_version_via", lambda *a, **k: "9.9.9")
    monkeypatch.setattr(upgrade_cmd, "_restart_and_verify", lambda **k: True)

    result = runner.invoke(_app(), ["upgrade"])
    assert result.exit_code == 0
    assert SOURCE_DIR_TEXT in result.stdout
    assert "scripts/install_source.sh" in result.stdout
    assert "Upgraded" in result.stdout


def test_no_source_install_notice_for_a_release_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(upgrade_cmd, "_run_upgrade_subprocess", _ok_run)
    monkeypatch.setattr(upgrade_cmd, "_installed_version_via", lambda *a, **k: "9.9.9")
    monkeypatch.setattr(upgrade_cmd, "_restart_and_verify", lambda **k: True)

    result = runner.invoke(_app(), ["upgrade"])
    assert result.exit_code == 0
    assert "install_source.sh" not in result.stdout


def test_dry_run_reports_the_source_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = {"run": False}
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(upgrade_cmd, "installed_from_directory", lambda *a, **k: SOURCE_DIR)
    monkeypatch.setattr(
        upgrade_cmd, "_run_upgrade_subprocess", lambda *a, **k: ran.__setitem__("run", True)
    )

    result = runner.invoke(_app(), ["upgrade", "--dry-run", "--json"])
    assert result.exit_code == 0
    assert _json_payload(result.stdout)["sourceDirectory"] == SOURCE_DIR_TEXT
    assert ran["run"] is False


def test_success_json_reports_the_source_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(upgrade_cmd, "installed_from_directory", lambda *a, **k: SOURCE_DIR)
    monkeypatch.setattr(upgrade_cmd, "_run_upgrade_subprocess", _ok_run)
    monkeypatch.setattr(upgrade_cmd, "_installed_version_via", lambda *a, **k: "9.9.9")
    monkeypatch.setattr(upgrade_cmd, "_restart_and_verify", lambda **k: True)

    result = runner.invoke(_app(), ["upgrade", "--json"])
    assert result.exit_code == 0
    payload = _json_payload(result.stdout)
    assert payload["sourceDirectory"] == SOURCE_DIR_TEXT
    assert payload["new"] == "9.9.9"


def test_release_install_json_reports_null_source_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(upgrade_cmd, "_run_upgrade_subprocess", _ok_run)
    monkeypatch.setattr(upgrade_cmd, "_installed_version_via", lambda *a, **k: "9.9.9")
    monkeypatch.setattr(upgrade_cmd, "_restart_and_verify", lambda **k: True)

    result = runner.invoke(_app(), ["upgrade", "--json"])
    assert result.exit_code == 0
    assert _json_payload(result.stdout)["sourceDirectory"] is None


# --- successful delegate + restart+verify ----------------------------------


def test_upgrade_success_restarts_and_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(upgrade_cmd, "_run_upgrade_subprocess", _ok_run)
    monkeypatch.setattr(upgrade_cmd, "_installed_version_via", lambda *a, **k: "99999.2.0")
    seen: dict[str, Any] = {}

    def fake_restart(**kwargs: Any) -> bool:
        seen.update(kwargs)
        return True

    monkeypatch.setattr(upgrade_cmd, "_restart_and_verify", fake_restart)
    result = runner.invoke(_app(), ["upgrade"])
    assert result.exit_code == 0
    assert "Upgraded:" in result.stdout
    assert "→ 99999.2.0" in result.stdout
    assert seen["expected_version"] == "99999.2.0"


def test_upgrade_verify_failure_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(upgrade_cmd, "_run_upgrade_subprocess", _ok_run)
    monkeypatch.setattr(upgrade_cmd, "_installed_version_via", lambda *a, **k: "99999.2.0")
    monkeypatch.setattr(upgrade_cmd, "_restart_and_verify", lambda **k: False)
    result = runner.invoke(_app(), ["upgrade"])
    assert result.exit_code == 1


# --- --no-restart ----------------------------------------------------------


def test_no_restart_loud_warning_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(upgrade_cmd, "_run_upgrade_subprocess", _ok_run)
    monkeypatch.setattr(upgrade_cmd, "_installed_version_via", lambda *a, **k: "99999.2.0")
    restarted = {"called": False}
    monkeypatch.setattr(
        upgrade_cmd,
        "_restart_and_verify",
        lambda **k: restarted.__setitem__("called", True),
    )
    result = runner.invoke(_app(), ["upgrade", "--no-restart"])
    assert result.exit_code == 0
    assert restarted["called"] is False
    # Loud warning, prefixed ⚠ (emitted to stderr; CliRunner merges streams).
    assert "⚠" in result.output
    assert "OLD version" in result.output


# --- timeout ---------------------------------------------------------------


def test_upgrade_timeout_exits_one_with_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(
        upgrade_cmd,
        "_run_upgrade_subprocess",
        lambda *a, **k: upgrade_cmd.UpgradeRunResult(
            ok=False, timed_out=True, returncode=None, stdout="", stderr=""
        ),
    )
    result = runner.invoke(_app(), ["upgrade"])
    assert result.exit_code == 1
    assert "timed out" in result.stdout
    assert "process group" in result.stdout


def test_upgrade_failure_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_cmd, "build_upgrade_plan", _delegated_plan)
    monkeypatch.setattr(
        upgrade_cmd,
        "_run_upgrade_subprocess",
        lambda *a, **k: upgrade_cmd.UpgradeRunResult(
            ok=False, timed_out=False, returncode=2, stdout="", stderr="boom"
        ),
    )
    result = runner.invoke(_app(), ["upgrade"])
    assert result.exit_code == 1
    assert "Upgrade failed" in result.stdout


# --- _kill_process_group ---------------------------------------------------


def test_kill_process_group_windows_uses_taskkill(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeProc:
        pid = 12345

        def kill(self) -> None:
            raise AssertionError("kill() should not be called if taskkill succeeds")

    executed_cmd: list[str] = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> Any:
        executed_cmd.extend(cmd)
        return None

    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr("subprocess.run", _fake_run)

    fake_proc = _FakeProc()
    upgrade_cmd._kill_process_group(fake_proc)  # type: ignore[arg-type]
    assert executed_cmd == ["taskkill", "/PID", "12345", "/T", "/F"]


def test_kill_process_group_windows_fallback_to_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    killed = {"called": False}

    class _FakeProc:
        pid = 12345

        def kill(self) -> None:
            killed["called"] = True

    def _failing_run(*args: Any, **kwargs: Any) -> Any:
        raise OSError("taskkill not found")

    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr("subprocess.run", _failing_run)

    fake_proc = _FakeProc()
    upgrade_cmd._kill_process_group(fake_proc)  # type: ignore[arg-type]
    assert killed["called"] is True


def test_run_upgrade_subprocess_windows_timeout_success_on_second_communicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    class MockPopen:
        last_kwargs: dict[str, Any] = {}

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            MockPopen.last_kwargs = kwargs
            self.pid = 9999
            self.returncode = None
            self.args = command
            self.communicate_calls: list[float | None] = []

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            self.communicate_calls.append(timeout)
            if len(self.communicate_calls) == 1:
                raise subprocess.TimeoutExpired(self.args, timeout)
            else:
                self.returncode = -15
                return "stdout after kill", "stderr after kill"

    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr(subprocess, "Popen", MockPopen)

    taskkill_called = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> Any:
        taskkill_called.append(cmd)
        return None

    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = upgrade_cmd._run_upgrade_subprocess(["dummy_cmd"], env={}, timeout=10.0)

    expected_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    assert MockPopen.last_kwargs.get("creationflags") == expected_flags
    assert taskkill_called == [["taskkill", "/PID", "9999", "/T", "/F"]]
    assert result.ok is False
    assert result.timed_out is True
    assert result.returncode == -15
    assert result.stdout == "stdout after kill"
    assert result.stderr == "stderr after kill"


def test_run_upgrade_subprocess_windows_timeout_secondary_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    class MockPopen:
        last_kwargs: dict[str, Any] = {}

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            MockPopen.last_kwargs = kwargs
            self.pid = 9999
            self.returncode = None
            self.args = command
            self.communicate_calls: list[float | None] = []

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            self.communicate_calls.append(timeout)
            if len(self.communicate_calls) == 1:
                raise subprocess.TimeoutExpired(self.args, timeout)
            else:
                raise subprocess.TimeoutExpired(
                    self.args, timeout, output="secondary stdout", stderr="secondary stderr"
                )

        def poll(self) -> int | None:
            self.returncode = -9
            return self.returncode

    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr(subprocess, "Popen", MockPopen)

    taskkill_called = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> Any:
        taskkill_called.append(cmd)
        return None

    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = upgrade_cmd._run_upgrade_subprocess(["dummy_cmd"], env={}, timeout=10.0)

    expected_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    assert MockPopen.last_kwargs.get("creationflags") == expected_flags
    assert taskkill_called == [["taskkill", "/PID", "9999", "/T", "/F"]]
    assert result.ok is False
    assert result.timed_out is True
    assert result.returncode == -9
    assert result.stdout == "secondary stdout"
    assert result.stderr == "secondary stderr"
