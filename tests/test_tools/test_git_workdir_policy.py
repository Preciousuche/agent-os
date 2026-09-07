from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentos.tools.builtin import git
from agentos.tools.types import ToolContext, ToolError, current_tool_context


def test_git_effective_workdir_resolves_context_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    try:
        assert git._effective_workdir(None) == str(workspace.resolve())
    finally:
        current_tool_context.reset(token)


def test_git_effective_workdir_rejects_foreign_posix_absolute_path_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(git, "os", SimpleNamespace(name="nt"), raising=False)
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    try:
        with pytest.raises(ToolError, match="foreign_host_path"):
            git._effective_workdir("/Users/a1/Desktop/repo")
    finally:
        current_tool_context.reset(token)


def test_git_rejects_foreign_diff_path_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(git, "os", SimpleNamespace(name="nt"), raising=False)

    with pytest.raises(ToolError, match="foreign_host_path"):
        git._reject_foreign_git_path("/Users/a1/Desktop/repo/file.py")


def test_git_rejects_foreign_commit_file_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(git, "os", SimpleNamespace(name="nt"), raising=False)

    with pytest.raises(ToolError, match="foreign_host_path"):
        git._reject_foreign_git_path("/Users/a1/Desktop/repo/file.py")


def test_git_diff_argv_unstaged_without_path() -> None:
    assert git._git_diff_argv({}) == ("git", "diff")
    assert git._git_diff_argv({"staged": False, "path": None}) == ("git", "diff")


def test_git_diff_argv_staged_without_path() -> None:
    assert git._git_diff_argv({"staged": True}) == ("git", "diff", "--cached")
    assert git._git_diff_argv({"staged": True, "path": None}) == ("git", "diff", "--cached")


def test_git_diff_argv_unstaged_with_path() -> None:
    assert git._git_diff_argv({"path": "src/main.py"}) == (
        "git",
        "diff",
        "--",
        "src/main.py",
    )


def test_git_diff_argv_staged_with_path() -> None:
    assert git._git_diff_argv({"staged": True, "path": "src/main.py"}) == (
        "git",
        "diff",
        "--cached",
        "--",
        "src/main.py",
    )


@pytest.mark.asyncio
async def test_git_commit_empty_files_skips_git_add(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded_commands: list[tuple[tuple[str, ...], str | None]] = []

    async def _mock_run_git(*args: str, cwd: str | None = None) -> str:
        recorded_commands.append((args, cwd))
        return "ok"

    monkeypatch.setattr(git, "_run_git", _mock_run_git)
    raw_git_commit = git.git_commit.__wrapped__.__wrapped__
    result = await raw_git_commit(message="commit only staged", files=[], workdir="/repo")
    assert result == "ok"
    assert recorded_commands == [
        (("diff", "--cached", "--name-only"), "/repo"),
        (("commit", "-m", "commit only staged"), "/repo"),
    ]


@pytest.mark.asyncio
async def test_git_commit_omitted_files_runs_git_add_all(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded_commands: list[tuple[tuple[str, ...], str | None]] = []

    async def _mock_run_git(*args: str, cwd: str | None = None) -> str:
        recorded_commands.append((args, cwd))
        return "ok"

    monkeypatch.setattr(git, "_run_git", _mock_run_git)
    raw_git_commit = git.git_commit.__wrapped__.__wrapped__
    result = await raw_git_commit(message="stage all", files=None, workdir="/repo")
    assert result == "ok"
    assert recorded_commands == [
        (("add", "-A"), "/repo"),
        (("diff", "--cached", "--name-only"), "/repo"),
        (("commit", "-m", "stage all"), "/repo"),
    ]


@pytest.mark.asyncio
async def test_git_commit_specific_files_stages_only_specified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded_commands: list[tuple[tuple[str, ...], str | None]] = []

    async def _mock_run_git(*args: str, cwd: str | None = None) -> str:
        recorded_commands.append((args, cwd))
        return "ok"

    monkeypatch.setattr(git, "_run_git", _mock_run_git)
    monkeypatch.setattr(git, "_reject_foreign_git_path", lambda p: None)
    raw_git_commit = git.git_commit.__wrapped__.__wrapped__
    result = await raw_git_commit(
        message="stage some", files=["file1.py", "file2.py"], workdir="/repo"
    )
    assert result == "ok"
    assert recorded_commands == [
        (("add", "--", "file1.py", "file2.py"), "/repo"),
        (("diff", "--cached", "--name-only"), "/repo"),
        (("commit", "-m", "stage some"), "/repo"),
    ]


@pytest.mark.asyncio
async def test_git_commit_reports_nothing_staged_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded_commands: list[tuple[tuple[str, ...], str | None]] = []

    async def _mock_run_git(*args: str, cwd: str | None = None) -> str:
        recorded_commands.append((args, cwd))
        if args[0] == "diff":
            return ""  # nothing staged
        return "ok"

    monkeypatch.setattr(git, "_run_git", _mock_run_git)
    raw_git_commit = git.git_commit.__wrapped__.__wrapped__
    result = await raw_git_commit(message="commit only staged", files=[], workdir="/repo")

    assert result == "Nothing staged to commit."
    # No commit was attempted against an empty index.
    assert recorded_commands == [(("diff", "--cached", "--name-only"), "/repo")]


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "file1.txt").write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "add", "file1.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)


def _porcelain_status(repo: Path, path: str) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", path],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


async def test_git_commit_empty_files_does_not_stage_untracked_files(tmp_path: Path) -> None:
    """End-to-end regression for #1203: files=[] must not fall through to
    `git add -A` and sweep an untracked file (e.g. a stray secrets file)
    into the commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    (repo / "file1.txt").write_text("modified\n", encoding="utf-8")
    subprocess.run(["git", "add", "file1.txt"], cwd=repo, check=True)
    (repo / "secret.txt").write_text("do-not-commit\n", encoding="utf-8")

    raw_git_commit = git.git_commit.__wrapped__.__wrapped__
    result = await raw_git_commit(message="commit staged only", files=[], workdir=str(repo))

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    assert "secret.txt" not in tracked
    assert _porcelain_status(repo, "secret.txt") == "?? secret.txt\n"
    assert "commit staged only" in result

    committed_file1 = subprocess.run(
        ["git", "show", "HEAD:file1.txt"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert committed_file1 == "modified\n"


async def test_git_commit_omitted_files_does_stage_untracked_files(tmp_path: Path) -> None:
    """Contrast case: files=None (omitted) is the one input that should
    still sweep in untracked files, per the documented `git add -A` default."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    (repo / "new_file.txt").write_text("brand new\n", encoding="utf-8")

    raw_git_commit = git.git_commit.__wrapped__.__wrapped__
    await raw_git_commit(message="stage everything", files=None, workdir=str(repo))

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    assert "new_file.txt" in tracked
