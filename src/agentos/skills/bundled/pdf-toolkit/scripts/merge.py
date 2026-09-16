"""Merge whole PDFs or page ranges from multiple PDFs.

Usage:
    merge.py a.pdf b.pdf --out combined.pdf
    merge.py manifest.json --out combined.pdf

Manifest schema:
    [{"file": "a.pdf", "pages": "1-3"},
     {"file": "b.pdf"}]

Pages past the end of an input are never dropped silently: the summary lists
them per file under ``skipped_pages``, and a merge that would write no page at
all is an error rather than a zero-page PDF.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def _write_stdout(text: str) -> None:
    """Write *text* to stdout as UTF-8, surviving a non-UTF-8 stdout encoding.

    ``print`` encodes through ``sys.stdout.encoding``, which on Windows is the
    console code page (cp1252, cp936, cp932) rather than UTF-8, so a character
    outside that page raises ``UnicodeEncodeError`` before a byte is written --
    the content decides whether the skill runs at all. The binary buffer is the
    primary path; a stream without a usable ``buffer`` -- a wrapper, or a
    captured stdout -- still gets the text, escaped rather than lost.
    """
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        try:
            buffer.write(text.encode("utf-8"))
            buffer.flush()
            return
        except (AttributeError, OSError, ValueError):
            # Buffer closed or not writable -- fall through to the text layer.
            pass

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    # Lossless: unencodable chars become escapes, not "?".
    sys.stdout.write(text.encode(encoding, errors="backslashreplace").decode(encoding))
    sys.stdout.flush()


def requested_pages(spec: str | None, total: int) -> list[int]:
    """Every page number *spec* asks for, in order, without clamping to *total*.

    ``parse_ranges`` drops what the document does not have; a caller that has to
    report the difference needs the unclamped list to subtract from.
    """
    if not spec:
        return list(range(1, total + 1))
    pages: list[int] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            lo_s, hi_s = token.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if lo > hi:
                lo, hi = hi, lo
            pages.extend(range(lo, hi + 1))
        else:
            pages.append(int(token))
    return pages


def parse_ranges(spec: str | None, total: int) -> list[int]:
    return [p for p in requested_pages(spec, total) if 1 <= p <= total]


@dataclass
class MergeResult:
    """What a merge actually wrote, including the pages it could not."""

    pages_written: int = 0
    skipped: list[tuple[str, list[int]]] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)


def merge(items: Iterable[dict[str, str]], out: Path) -> MergeResult:
    """Merge *items* into *out*, reporting what did not make it in.

    The output file is written only when at least one page went into it. A
    zero-page PDF is not a merge that succeeded with nothing to do -- it is a
    merge whose every input was missing or out of range, and leaving a valid
    but empty file behind lets that pass for success.
    """
    writer = PdfWriter()
    result = MergeResult()
    for item in items:
        path = Path(item["file"])
        if not path.is_file():
            print(f"warn: missing {path}", file=sys.stderr)
            result.missing_files.append(str(path))
            continue
        reader = PdfReader(str(path))
        total = len(reader.pages)
        skipped = [p for p in requested_pages(item.get("pages"), total) if not 1 <= p <= total]
        if skipped:
            result.skipped.append((str(path), skipped))
        for page_num in parse_ranges(item.get("pages"), total):
            writer.add_page(reader.pages[page_num - 1])
            result.pages_written += 1
    if result.pages_written == 0:
        return result
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        writer.write(fh)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge PDFs or page ranges.")
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Either N PDF paths, or one .json manifest path",
    )
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    items: list[dict[str, str]]
    if len(args.inputs) == 1 and args.inputs[0].endswith(".json"):
        manifest_path = Path(args.inputs[0])
        if not manifest_path.is_file():
            print(f"error: manifest {manifest_path} not found", file=sys.stderr)
            return 2
        items = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            print("error: manifest must be a JSON array", file=sys.stderr)
            return 2
    else:
        items = [{"file": p} for p in args.inputs]
    result = merge(items, args.out)
    if result.pages_written == 0:
        print(
            f"error: no requested page exists in any input; nothing written to {args.out}",
            file=sys.stderr,
        )
        return 2
    for file_name, pages in result.skipped:
        dropped = ", ".join(str(p) for p in pages)
        print(f"warn: {file_name} has no page {dropped}", file=sys.stderr)
    _write_stdout(
        json.dumps(
            {
                "pages_written": result.pages_written,
                "out": str(args.out),
                "skipped_pages": [
                    {"file": file_name, "pages": pages} for file_name, pages in result.skipped
                ],
                "missing_files": result.missing_files,
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
