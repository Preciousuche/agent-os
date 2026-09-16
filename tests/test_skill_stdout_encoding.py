"""Issue #2334: bundled skill scripts crashed emitting non-ASCII to stdout.

``print`` and ``sys.stdout.write`` encode through ``sys.stdout.encoding``. On
Windows that is the console code page — cp1252 here, cp936/cp932 on CJK
systems — not UTF-8, and it is what a *piped* stdout falls back to, which is
how a skill's output is captured. Any character outside that page raises
``UnicodeEncodeError`` before a byte is written, so the document decides
whether the skill runs:

    File ".../inspect_xlsx.py", line 88, in main
        print(text)
    UnicodeEncodeError: 'charmap' codec can't encode characters in position
    154-155: character maps to <undefined>

Each script's ``--out`` branch already passed ``encoding="utf-8"``, which is
what made the stdout branch the odd one out rather than a platform limit.

``_write_stdout`` is the helper #1835 merged for ``git-diff`` and ``pptx``,
applied to the rest of the fleet: the binary buffer is the primary path, and a
stream without a usable ``buffer`` still gets the text with ``backslashreplace``
rather than an exception.

Three groups are covered. The nine scripts that reach stdout via
``print(json.dumps(..., ensure_ascii=False))`` are the ones named in #2334. Six
more reach it through ``sys.stdout.write`` — a form the AST scan behind that
issue did not match, so they went unreported: ``http_fetch`` writing a decoded
web page, ``search`` writing result titles, ``weather_fetch`` writing a location
name, and the three cron watchers printing feed, issue and JSON-field text. The
last eight were found by the sweep at the bottom of this file rather than by
hand, which is the argument for having it.
"""

from __future__ import annotations

import ast
import importlib
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "agentos" / "skills" / "bundled"

#: Scripts named in #2334 — ``print(json.dumps(..., ensure_ascii=False))``.
JSON_PRINTERS = (
    "docx/scripts/edit_docx.py",
    "docx/scripts/inspect_docx.py",
    "pdf-toolkit/scripts/extract.py",
    "pdf-toolkit/scripts/form_fill.py",
    "pdf-toolkit/scripts/merge.py",
    "pdf-toolkit/scripts/split.py",
    "robinhood-chain-stocks/scripts/chain_stocks.py",
    "robinhood-rwa-addresses/scripts/rwa_lookup.py",
    "xlsx/scripts/edit_xlsx.py",
)

#: Reached stdout via ``sys.stdout.write`` instead, so #2334 did not list them.
STREAM_WRITERS = (
    "http-fetch/scripts/http_fetch.py",
    "multi-search-engine/scripts/search.py",
    "weather/scripts/weather_fetch.py",
    "cron-watchers/scripts/watch_rss.py",
    "cron-watchers/scripts/watch_github.py",
    "cron-watchers/scripts/watch_http_json.py",
)

#: Found by ``test_the_covered_list_matches_what_is_actually_in_the_tree``
#: below rather than by hand — the reason that test exists. Token symbols,
#: image and video prompts, and rendered card text all carry non-ASCII.
FOUND_BY_THE_SWEEP = (
    "deep-research/scripts/iterate.py",
    "deep-research/scripts/plan.py",
    "gmgn-market/scripts/kline_chart.py",
    "gmgn-token/scripts/kline_chart.py",
    "nano-banana-pro/scripts/generate_image.py",
    "robinhood-chain-stocks/scripts/chain_cards.py",
    "robinhood-rwa-addresses/scripts/rwa_cards.py",
    "seedance-2-prompt/scripts/generate_video.py",
)

COVERED = JSON_PRINTERS + STREAM_WRITERS + FOUND_BY_THE_SWEEP

#: Already carry the helper, from #1835 and the in-tree original.
ALREADY_FIXED = (
    "git-diff/scripts/git_diff.py",
    "pptx/scripts/extract_text.py",
    "text-file-read/scripts/read.py",
)

#: Same defect, reported and fixed under their own issues.
SEPARATE_ISSUES = (
    "xlsx/scripts/inspect_xlsx.py",  # #2264
    "history-explorer/scripts/explore.py",  # #2287
)

SAMPLE = "日本語 café 🎉 — em-dash"


def load(rel: str):
    """Import a bundled script the way it runs: by name, from its own dir."""
    path = BUNDLED / rel
    sys.path.insert(0, str(path.parent))
    try:
        sys.modules.pop(path.stem, None)
        return importlib.import_module(path.stem)
    finally:
        sys.path.pop(0)


class _CodePageStdout(io.TextIOWrapper):
    """A stdout whose text layer is a Windows code page, like a piped console."""

    def __init__(self, encoding: str = "cp1252") -> None:
        self._sink = io.BytesIO()
        super().__init__(self._sink, encoding=encoding, newline="")

    def captured(self) -> bytes:
        self.flush()
        return self._sink.getvalue()


# ── every covered script has the helper, and it survives a code-page stdout ──


@pytest.mark.parametrize(
    "rel", COVERED, ids=[r.split("/")[0] + ":" + Path(r).stem for r in COVERED]
)
def test_the_script_exposes_the_helper(rel: str) -> None:
    assert hasattr(load(rel), "_write_stdout"), f"{rel} has no _write_stdout"


@pytest.mark.parametrize("rel", COVERED, ids=[Path(r).stem for r in COVERED])
@pytest.mark.parametrize("code_page", ["cp1252", "cp936", "cp932", "ascii"])
def test_non_ascii_survives_every_code_page(
    rel: str, code_page: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bytes on the wire are UTF-8 whatever the console claims to be.

    cp1252 swallows Latin-1 but not CJK; cp936 the reverse; ``ascii`` is what a
    bare POSIX ``C`` locale gives. All three used to raise.
    """
    module = load(rel)
    stream = _CodePageStdout(code_page)
    monkeypatch.setattr(sys, "stdout", stream)

    module._write_stdout(SAMPLE)

    assert stream.captured() == SAMPLE.encode("utf-8")


@pytest.mark.parametrize("rel", COVERED, ids=[Path(r).stem for r in COVERED])
def test_the_helper_does_not_raise_on_a_code_page_stdout(
    rel: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression in one line: this raised UnicodeEncodeError."""
    module = load(rel)
    monkeypatch.setattr(sys, "stdout", _CodePageStdout("cp1252"))

    module._write_stdout(SAMPLE)  # must not raise


# ── the fallback path, for a stream with no usable buffer ───────────────────


class _NoBuffer(io.StringIO):
    """A captured stdout — pytest's capsys, or any wrapper — has no ``buffer``."""

    encoding = "cp1252"


class _BrokenBuffer(io.StringIO):
    """A stream whose ``buffer`` exists but refuses writes."""

    encoding = "cp1252"

    @property
    def buffer(self):  # noqa: D102
        class _B:
            @staticmethod
            def write(_data):
                raise ValueError("closed")

            @staticmethod
            def flush():
                return None

        return _B()


@pytest.mark.parametrize("rel", COVERED, ids=[Path(r).stem for r in COVERED])
def test_a_stream_without_a_buffer_gets_escaped_text_not_an_exception(
    rel: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lossless degradation: unencodable characters become ``\\uXXXX`` escapes,
    never ``?`` and never a raise."""
    module = load(rel)
    stream = _NoBuffer()
    monkeypatch.setattr(sys, "stdout", stream)

    module._write_stdout(SAMPLE)

    written = stream.getvalue()
    assert "café" in written  # cp1252 can represent this
    assert "\\u65e5" in written  # 日 escaped rather than lost
    assert "?" not in written


@pytest.mark.parametrize("rel", COVERED, ids=[Path(r).stem for r in COVERED])
def test_a_buffer_that_refuses_writes_falls_through(
    rel: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closed or non-writable buffer must not take the output down with it."""
    module = load(rel)
    stream = _BrokenBuffer()
    monkeypatch.setattr(sys, "stdout", stream)

    module._write_stdout(SAMPLE)

    assert stream.getvalue()


@pytest.mark.parametrize("rel", COVERED, ids=[Path(r).stem for r in COVERED])
def test_pure_ascii_is_unchanged(rel: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The overwhelmingly common case must be byte-identical to ``print``."""
    module = load(rel)
    stream = _CodePageStdout("cp1252")
    monkeypatch.setattr(sys, "stdout", stream)

    module._write_stdout('{"ok": true}\n')

    assert stream.captured() == b'{"ok": true}\n'


# ── no covered script still reaches stdout unguarded ────────────────────────


def _unguarded_stdout_sites(path: Path) -> list[tuple[int, str]]:
    """``print(<dynamic>)`` / ``sys.stdout.write(...)`` outside the helper."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    sites: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if any(kw.arg == "file" for kw in node.keywords):
            continue  # stderr is a separate stream and defaults to backslashreplace
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            if node.args and isinstance(node.args[0], ast.Constant):
                continue  # a fixed ASCII banner cannot carry non-ASCII
            sites.append((node.lineno, "print"))
        if isinstance(node.func, ast.Attribute) and node.func.attr == "write":
            rendered = ast.unparse(node.func)
            if "stdout" in rendered and "buffer" not in rendered:
                if "errors=" in ast.unparse(node):
                    continue  # the helper's own fallback
                sites.append((node.lineno, "sys.stdout.write"))
    return sites


@pytest.mark.parametrize("rel", COVERED + ALREADY_FIXED, ids=lambda r: Path(r).stem)
def test_no_unguarded_stdout_write_remains(rel: str) -> None:
    """The guard that stops this class coming back one script at a time.

    #1834 fixed two scripts, #2264 a third, #2287 a fourth, and #2334 found
    nine more. Asserting the absence structurally is what makes the next one
    fail here instead of in front of a user.
    """
    sites = _unguarded_stdout_sites(BUNDLED / rel)

    assert sites == [], f"{rel} still emits to stdout unguarded at {sites}"


def test_the_covered_list_matches_what_is_actually_in_the_tree() -> None:
    """A script added later with the same defect should widen this list.

    Scans every bundled script, subtracts the ones covered here, the ones
    already fixed, and the two tracked under their own issues. Anything left
    is a gap — and the message names it.
    """
    known = {*COVERED, *ALREADY_FIXED, *SEPARATE_ISSUES}
    gaps: list[str] = []
    for path in sorted(BUNDLED.rglob("*.py")):
        rel = path.relative_to(BUNDLED).as_posix()
        if rel in known or "selftest" in rel:
            continue
        source = path.read_text(encoding="utf-8")
        # Only scripts that can actually carry non-ASCII: they build JSON with
        # ensure_ascii=False, or write decoded input straight out.
        if "ensure_ascii=False" not in source:
            continue
        if _unguarded_stdout_sites(path):
            gaps.append(rel)

    assert gaps == [], f"bundled scripts emit non-ASCII to stdout unguarded: {gaps}"


# ── end to end, through the scripts the issue reproduced ────────────────────


def test_inspect_docx_prints_a_cjk_document(tmp_path: Path, capsysbinary) -> None:
    """The issue's second reproduction. ``python inspect_docx.py doc.docx`` with
    no ``--out`` is the invocation SKILL.md documents."""
    from docx import Document

    doc = Document()
    doc.add_paragraph("日本語のテキスト café")
    source = tmp_path / "cjk.docx"
    doc.save(str(source))

    module = load("docx/scripts/inspect_docx.py")
    sys_argv = ["inspect_docx.py", str(source)]
    original = sys.argv
    sys.argv = sys_argv
    try:
        assert module.main() == 0
    finally:
        sys.argv = original

    out = capsysbinary.readouterr().out.decode("utf-8")
    assert "日本語のテキスト café" in json.dumps(json.loads(out), ensure_ascii=False)


def test_extract_prints_cjk_pdf_metadata(tmp_path: Path, capsysbinary) -> None:
    """Non-ASCII *metadata* is enough; the PDF needs no text layer."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "日本語のタイトル", "/Author": "café"})
    source = tmp_path / "cjk.pdf"
    with source.open("wb") as handle:
        writer.write(handle)

    module = load("pdf-toolkit/scripts/extract.py")
    original = sys.argv
    sys.argv = ["extract.py", str(source)]
    try:
        assert module.main() == 0
    finally:
        sys.argv = original

    payload = json.loads(capsysbinary.readouterr().out.decode("utf-8"))
    assert payload["metadata"]["Title"] == "日本語のタイトル"


def test_the_out_branch_was_never_broken_and_still_is_not(tmp_path: Path) -> None:
    """The ``--out`` path already passed ``encoding="utf-8"``. Pinned so the
    stdout fix is not mistaken for having changed it."""
    from docx import Document

    doc = Document()
    doc.add_paragraph("日本語")
    source = tmp_path / "cjk.docx"
    doc.save(str(source))
    out = tmp_path / "o.json"

    module = load("docx/scripts/inspect_docx.py")
    original = sys.argv
    sys.argv = ["inspect_docx.py", str(source), "--out", str(out)]
    try:
        assert module.main() == 0
    finally:
        sys.argv = original

    assert "日本語" in out.read_text(encoding="utf-8")
