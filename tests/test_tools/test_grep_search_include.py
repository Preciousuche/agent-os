"""grep_search's `include` glob: path-qualified patterns and the bare-filename form.

Issue #1571: `include` was matched against `fp.name` only via
`fnmatch.fnmatch(fp.name, include)`. Since `fp.name` never contains a
directory separator, any path-qualified pattern ("tests/*.py",
"src/**/*.ts") matched nothing and grep_search silently reported no
matches, indistinguishable from "this code doesn't exist".
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from agentos.tools.builtin import filesystem as fs
from agentos.tools.types import CallerKind, ToolContext, current_tool_context


@contextmanager
def tool_context(workspace: Path) -> Iterator[None]:
    token = current_tool_context.set(
        ToolContext(
            caller_kind=CallerKind.CLI,
            channel_kind="cli",
            channel_id="cli:test",
            workspace_dir=str(workspace),
            workspace_strict=True,
        )
    )
    try:
        yield
    finally:
        current_tool_context.reset(token)


def _layout(base: Path) -> None:
    (base / "tests").mkdir()
    (base / "src" / "utils").mkdir(parents=True)
    (base / "tests" / "test_basic.py").write_text("def test_foo():\n    pass\n")
    (base / "src" / "utils.py").write_text("import os\n")
    (base / "src" / "utils" / "helpers.py").write_text("import sys\n")
    (base / "notes.txt").write_text("import not-python\n")


@pytest.mark.asyncio
async def test_path_qualified_include_matches_the_relative_path(tmp_path: Path) -> None:
    """Issue #1571's exact reproduction: a path-qualified include used to
    match nothing at all."""
    _layout(tmp_path)

    with tool_context(tmp_path):
        result = await fs.grep_search("def test_", include="tests/*.py")

    assert "test_basic.py" in result
    assert "No matches" not in result


@pytest.mark.asyncio
async def test_bare_filename_include_still_matches_at_any_depth(tmp_path: Path) -> None:
    """Non-regression: fnmatch's `*` already spans `/`, so the documented
    bare-filename form ('*.py') must keep matching files at every depth,
    not just those directly under the search root."""
    _layout(tmp_path)

    with tool_context(tmp_path):
        result = await fs.grep_search("import", include="*.py")

    assert "utils.py" in result
    assert "helpers.py" in result
    assert "notes.txt" not in result


@pytest.mark.asyncio
async def test_recursive_path_qualified_include_matches_nested_files(tmp_path: Path) -> None:
    """fnmatch has no special recursive-`**` handling -- it is just two
    consecutive `*` either side of a literal `/`, which requires an extra
    path segment. "src/**/*.py" therefore matches src/utils/helpers.py
    (two segments under src) but not src/utils.py (only one)."""
    _layout(tmp_path)

    with tool_context(tmp_path):
        result = await fs.grep_search("import", include="src/**/*.py")

    assert "helpers.py" in result
    assert "utils.py" not in result
    assert "test_basic.py" not in result
    assert "notes.txt" not in result


@pytest.mark.asyncio
async def test_path_qualified_include_excludes_non_matching_directories(tmp_path: Path) -> None:
    _layout(tmp_path)

    with tool_context(tmp_path):
        result = await fs.grep_search("import", include="tests/*.py")

    assert "No matches" in result
