"""Dump `.docx` structure as JSON for LLM consumption.

Stdlib + python-docx only. Cross-platform, stateless, exits 0 on success.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from docx import Document


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


def inspect(path: Path) -> dict[str, Any]:
    doc = Document(str(path))

    paragraphs: list[dict[str, Any]] = []
    for idx, para in enumerate(doc.paragraphs):
        paragraphs.append(
            {
                "index": idx,
                "text": para.text,
                "style": para.style.name if para.style is not None else "",
                "runs": [
                    {"text": run.text, "bold": bool(run.bold), "italic": bool(run.italic)}
                    for run in para.runs
                ],
            }
        )

    tables: list[list[list[str]]] = []
    for tbl in doc.tables:
        tables.append([[cell.text for cell in row.cells] for row in tbl.rows])

    body_xml = doc.element.body.xml if doc.element is not None else ""
    has_tracked_changes = "<w:ins" in body_xml or "<w:del" in body_xml

    return {
        "paragraphs": paragraphs,
        "tables": tables,
        "sections": len(doc.sections),
        "has_tracked_changes": has_tracked_changes,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dump .docx structure as JSON.")
    parser.add_argument("path", type=Path, help="Path to a .docx file")
    parser.add_argument(
        "--out", type=Path, default=None, help="Optional output JSON path; default stdout"
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.path.is_file():
        print(f"error: {args.path} not found", file=sys.stderr)
        return 2
    payload = inspect(args.path)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        _write_stdout(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
