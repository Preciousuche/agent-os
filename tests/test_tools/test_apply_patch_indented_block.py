"""Issue #2799: an indented patch block applied as "no changes".

A patch nested in a Markdown list, a blockquote or an indented code block
arrives with every line pushed right. ``_marker_span`` found the indented
``*** Begin Patch`` / ``*** End Patch`` pair, but the body parser matched
directives and diff prefixes at column zero, so it recognised nothing:
``_parse_patch`` returned ``[]``, ``apply_patch`` reported ``Applied patch:
no changes``, and the workspace stayed untouched while the tool reported
success.

The block is now dedented by the indentation its **directive** lines share.
That reference is deliberate: a malformed content line indented *less* than
the directives cannot shrink the prefix and leave the directives indented --
which would be the same silent drop again -- so it is left as written and the
block parser reports it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from agentos.tools.builtin import patch as patch_tool
from agentos.tools.types import ToolContext, current_tool_context


def _original_async(fn: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
    return fn.__wrapped__.__wrapped__  # type: ignore[attr-defined, no-any-return]


async def _apply(workspace: Path, patch_text: str) -> str:
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    try:
        return await _original_async(patch_tool.apply_patch)(patch_text)
    finally:
        current_tool_context.reset(token)


def _indent(text: str, prefix: str) -> str:
    """Push every non-empty line of a flush patch right by *prefix*."""
    return "".join(f"{prefix}{line}\n" if line else "\n" for line in text.split("\n"))


ADD = "*** Begin Patch\n*** Add File: sample.txt\n+hello world\n*** End Patch"


# ── the issue ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_issues_four_space_block_creates_the_file(tmp_path: Path) -> None:
    result = await _apply(tmp_path, _indent(ADD, "    "))

    assert result == "Applied patch: 1 file(s) added"
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "hello world"


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", [" ", "  ", "    ", "        ", "\t", "\t\t", "  \t"])
async def test_any_consistent_indentation_is_stripped(tmp_path: Path, prefix: str) -> None:
    result = await _apply(tmp_path, _indent(ADD, prefix))

    assert result == "Applied patch: 1 file(s) added"
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "hello world"


def test_an_indented_block_no_longer_parses_to_nothing() -> None:
    """The silent half of the issue, pinned at the parser."""
    ops = patch_tool._parse_patch(_indent(ADD, "    "))

    assert [type(op).__name__ for op in ops] == ["AddFile"]


# ── the content's own indentation is untouched ──────────────────────────────


@pytest.mark.asyncio
async def test_inner_code_indentation_is_preserved(tmp_path: Path) -> None:
    patch = (
        "*** Begin Patch\n"
        "*** Add File: mod.py\n"
        "+def f():\n"
        "+    if True:\n"
        "+        return 1\n"
        "+\n"
        "+\tx = 2\n"
        "*** End Patch"
    )

    await _apply(tmp_path, _indent(patch, "    "))

    assert (tmp_path / "mod.py").read_text(encoding="utf-8") == (
        "def f():\n    if True:\n        return 1\n\n\tx = 2"
    )


@pytest.mark.asyncio
async def test_a_hunk_context_line_keeps_its_leading_space_as_the_diff_prefix(
    tmp_path: Path,
) -> None:
    """A context line is ``" " + text``; after dedent that space must survive."""
    target = tmp_path / "f.txt"
    target.write_text("keep\nold\nend\n", encoding="utf-8")
    patch = (
        "*** Begin Patch\n"
        "*** Update File: f.txt\n"
        "@@@ -1,3 +1,3 @@@\n"
        " keep\n"
        "-old\n"
        "+new\n"
        " end\n"
        "*** End Patch"
    )

    result = await _apply(tmp_path, _indent(patch, "    "))

    assert result == "Applied patch: 1 file(s) modified"
    assert target.read_text(encoding="utf-8") == "keep\nnew\nend\n"


@pytest.mark.asyncio
async def test_a_context_line_for_a_blank_source_line_survives(tmp_path: Path) -> None:
    """``" "`` alone -- a context line for an empty line -- becomes, after the
    block indent, a whitespace-only line one column longer than the indent.
    It must dedent to ``" "``, not be dropped as blank."""
    target = tmp_path / "f.txt"
    target.write_text("a\n\nb\n", encoding="utf-8")
    patch = (
        "*** Begin Patch\n*** Update File: f.txt\n@@@ -1,3 +1,3 @@@\n a\n \n-b\n+c\n*** End Patch"
    )

    await _apply(tmp_path, _indent(patch, "    "))

    assert target.read_text(encoding="utf-8") == "a\n\nc\n"


# ── every op kind, several ops ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_update_and_delete_all_apply_from_one_indented_block(tmp_path: Path) -> None:
    (tmp_path / "u.txt").write_text("old\n", encoding="utf-8")
    (tmp_path / "d.txt").write_text("gone\n", encoding="utf-8")
    patch = (
        "*** Begin Patch\n"
        "*** Add File: a.txt\n"
        "+added\n"
        "*** Update File: u.txt\n"
        "@@@ -1,1 +1,1 @@@\n"
        "-old\n"
        "+new\n"
        "*** Delete File: d.txt\n"
        "*** End Patch"
    )

    result = await _apply(tmp_path, _indent(patch, "  "))

    assert result == "Applied patch: 1 file(s) added, 1 file(s) modified, 1 file(s) deleted"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "added"
    assert (tmp_path / "u.txt").read_text(encoding="utf-8") == "new\n"
    assert not (tmp_path / "d.txt").exists()


# ── the shapes a Markdown context produces ──────────────────────────────────


@pytest.mark.asyncio
async def test_a_body_indented_deeper_than_its_markers(tmp_path: Path) -> None:
    """A nested list item: the block's lines sit one level in from the markers."""
    patch = "  *** Begin Patch\n      *** Add File: n.txt\n      +nested\n  *** End Patch\n"

    result = await _apply(tmp_path, patch)

    assert result == "Applied patch: 1 file(s) added"
    assert (tmp_path / "n.txt").read_text(encoding="utf-8") == "nested"


@pytest.mark.asyncio
async def test_a_drifted_begin_marker_over_a_flush_body_still_applies(tmp_path: Path) -> None:
    """The shape ``test_apply_patch_markers.py`` already supports: the marker
    drifted right, the body flush. Dedenting by the directives' indent -- zero
    here -- leaves it as it was."""
    patch = "  *** Begin Patch\n*** Add File: f.txt\n+flush\n*** End Patch\n"

    result = await _apply(tmp_path, patch)

    assert result == "Applied patch: 1 file(s) added"


@pytest.mark.asyncio
async def test_a_blank_line_trimmed_shorter_than_the_indent_is_an_empty_content_line(
    tmp_path: Path,
) -> None:
    """Editors strip trailing whitespace, so a blank line inside an indented
    block often arrives with *less* indentation than its neighbours."""
    patch = (
        "    *** Begin Patch\n    *** Add File: b.txt\n    +one\n\n    +two\n    *** End Patch\n"
    )

    await _apply(tmp_path, patch)

    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "one\n\ntwo"


@pytest.mark.asyncio
async def test_a_preamble_before_an_indented_block_is_ignored(tmp_path: Path) -> None:
    patch = "Here is the change:\n\n" + _indent(ADD, "    ") + "\nThat's all."

    result = await _apply(tmp_path, patch)

    assert result == "Applied patch: 1 file(s) added"


@pytest.mark.asyncio
async def test_crlf_and_indentation_together(tmp_path: Path) -> None:
    patch = _indent(ADD, "    ").replace("\n", "\r\n")

    result = await _apply(tmp_path, patch)

    assert result == "Applied patch: 1 file(s) added"


@pytest.mark.asyncio
async def test_an_end_marker_quoted_in_indented_content_does_not_close_the_block(
    tmp_path: Path,
) -> None:
    """The marker rule from ``_marker_span`` still holds after dedent: a quoted
    marker is a content line, one column past the block."""
    patch = (
        "    *** Begin Patch\n"
        "    *** Add File: q.txt\n"
        "    +*** End Patch\n"
        "    +after\n"
        "    *** End Patch\n"
    )

    await _apply(tmp_path, patch)

    assert (tmp_path / "q.txt").read_text(encoding="utf-8") == "*** End Patch\nafter"


# ── malformed input is reported, never silently dropped ─────────────────────


@pytest.mark.asyncio
async def test_a_content_line_indented_less_than_the_directives_is_an_error_not_a_no_op(
    tmp_path: Path,
) -> None:
    """The differentiator: measured on every line, a stray under-indented
    content line would shrink the prefix, leave the directives indented, and
    reproduce the issue -- ``no changes`` with a clean exit. Measured on the
    directives, the block dedents and the stray line is reported."""
    patch = "    *** Begin Patch\n    *** Add File: a.txt\n  +x\n    *** End Patch\n"

    with pytest.raises(ValueError, match="Invalid line in '\\*\\*\\* Add File: a.txt'"):
        patch_tool._parse_patch(patch)
    assert not (tmp_path / "a.txt").exists()


def test_nothing_is_ever_lstripped() -> None:
    """A line that does not carry the block indent is left exactly as written."""
    body = ["    *** Add File: a", "    +x", "  +y", "", "   "]

    assert patch_tool._dedent_block(body) == ["*** Add File: a", "+x", "  +y", "", "   "]


# ── the helpers ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ([], ""),
        (["*** Add File: a", "+x"], ""),
        (["    *** Add File: a", "    +x"], "    "),
        (["\t*** Add File: a", "\t+x"], "\t"),
        (["    *** Add File: a", "      *** Add File: b"], "    "),
        (["      *** Add File: a", "    *** Add File: b"], "    "),
        (["    *** Add File: a", "  +x"], "    "),  # content does not shrink it
        (["    *** Add File: a", "\t*** Add File: b"], ""),  # no common prefix
        (["    +only content, no directive"], ""),
    ],
)
def test_block_indent(body: list[str], expected: str) -> None:
    assert patch_tool._block_indent(body) == expected


def test_a_context_line_that_looks_like_a_directive_cannot_widen_the_indent() -> None:
    """`` *** Add File: x`` as a *hunk context line* sits one column past the
    directives; the common prefix is still the directives' own."""
    body = ["    *** Update File: f", "    @@@ -1 +1 @@@", "     *** Add File: x", "    +y"]

    assert patch_tool._block_indent(body) == "    "


def test_dedent_is_a_no_op_for_a_flush_block() -> None:
    body = ["*** Add File: a", "+x", " ctx", "-old"]

    assert patch_tool._dedent_block(body) is body
