"""Stage 2 of deep-research: print fetch list and record evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Re-use the model definitions from plan.py via path import.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from plan import DEPTHS, Plan, Source  # type: ignore[import-not-found]  # noqa: E402


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


def load_plan(path: Path) -> Plan:
    return Plan.model_validate_json(path.read_text(encoding="utf-8"))


def save_plan(plan: Plan, path: Path) -> None:
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")


def under_target(plan: Plan) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for sq in plan.subquestions:
        gap = sq.target_sources - len(sq.sources)
        if gap > 0:
            out.append(
                {
                    "subquestion_id": sq.id,
                    "question": sq.question,
                    "needs": gap,
                    "have": len(sq.sources),
                    "target": sq.target_sources,
                }
            )
    return out


def record_evidence(plan: Plan, evidence: list[dict[str, object]]) -> int:
    by_id = {sq.id: sq for sq in plan.subquestions}
    added = 0
    for item in evidence:
        sq_id = str(item.get("subquestion_id", ""))
        if sq_id not in by_id:
            continue
        sq = by_id[sq_id]
        sq.sources.append(
            Source(
                url=str(item.get("url", "")),
                title=str(item.get("title", "")),
                excerpt=str(item.get("excerpt", "")),
                relevance=float(item.get("relevance", 0.0)),
                fetched_at=str(item.get("fetched_at", "")),
            )
        )
        added += 1
    plan.rounds = max(plan.rounds, plan.rounds + 0)
    if all(sq.coverage() >= 1.0 for sq in plan.subquestions):
        plan.done = True
    return added


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 2 of deep-research.")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--round", type=int, default=1, dest="round_num")
    parser.add_argument(
        "--print-fetches",
        action="store_true",
        help="Emit the list of subquestions still under target as JSON",
    )
    parser.add_argument(
        "--record",
        type=Path,
        default=None,
        help="Path to a JSON file with this round's evidence",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.plan.is_file():
        print(f"error: plan {args.plan} not found", file=sys.stderr)
        return 2
    plan = load_plan(args.plan)
    plan.rounds = max(plan.rounds, args.round_num)

    if args.print_fetches and not args.record:
        _write_stdout(
            json.dumps(
                {
                    "round": args.round_num,
                    "fetches": under_target(plan),
                    "overall_coverage": plan.overall_coverage(),
                    "depth": plan.depth,
                    "depth_targets": DEPTHS[plan.depth],
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.record:
        if not args.record.is_file():
            print(f"error: record {args.record} not found", file=sys.stderr)
            return 2
        raw = json.loads(args.record.read_text(encoding="utf-8"))
        evidence = raw if isinstance(raw, list) else []
        added = record_evidence(plan, evidence)
        save_plan(plan, args.plan)
        _write_stdout(
            json.dumps(
                {
                    "round": args.round_num,
                    "added": added,
                    "overall_coverage": plan.overall_coverage(),
                    "done": plan.done,
                },
                ensure_ascii=False,
            )
        )
        return 0

    print(
        "error: pass --print-fetches or --record",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
