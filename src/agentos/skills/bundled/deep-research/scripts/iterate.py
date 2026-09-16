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


class InputError(ValueError):
    """An input file that cannot be used.

    Reported as ``error:`` / exit 2, never as a traceback: the caller passed
    bad input, the script did not break.
    """


def load_plan(path: Path) -> Plan:
    return Plan.model_validate_json(path.read_text(encoding="utf-8"))


def load_plan_file(path: Path) -> Plan:
    """Read and validate a plan file, or raise :class:`InputError`.

    ``model_validate_json`` raises ``pydantic.ValidationError`` (a
    ``ValueError``) for malformed JSON *and* for JSON that does not match the
    plan schema, and ``read_text`` raises ``UnicodeDecodeError`` for a file
    that is not UTF-8. All three reached the operator as a traceback.
    """
    try:
        return load_plan(path)
    except (ValueError, UnicodeDecodeError, OSError) as exc:
        raise InputError(f"plan {path} is not valid JSON or plan schema: {exc}") from exc


def load_evidence(path: Path, plan: Plan) -> list[dict[str, object]]:
    """Read and validate an evidence record file, or raise :class:`InputError`.

    The old ``raw if isinstance(raw, list) else []`` turned every non-list
    payload into "recorded nothing", saved the plan anyway and reported
    success, so a round's findings vanished with exit 0. A single evidence
    object -- the obvious thing to pass -- is the common way to hit it.

    Each item is checked before anything is written, so a bad record leaves
    the plan exactly as it was. Validating up front rather than skipping as we
    go is the whole point: ``record_evidence`` silently ``continue``\\ d past an
    item whose ``subquestion_id`` did not match, which turns a typo into
    quietly missing evidence, and it accepted an item with no ``url`` at all,
    which writes a source pointing nowhere.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise InputError(f"record {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise InputError(
            f"record {path} must be a JSON list of evidence items, got {type(raw).__name__}"
        )

    known = {sq.id for sq in plan.subquestions}
    items: list[dict[str, object]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise InputError(
                f"record entry {index} must be an object with a "
                f'"subquestion_id" and a "url", got {type(item).__name__}'
            )
        subquestion_id = item.get("subquestion_id")
        if not isinstance(subquestion_id, str) or not subquestion_id.strip():
            raise InputError(f'record entry {index} is missing a "subquestion_id"')
        if subquestion_id not in known:
            raise InputError(
                f"record entry {index} names unknown subquestion_id "
                f"{subquestion_id!r}; this plan has {', '.join(sorted(known))}"
            )
        url = item.get("url")
        if not isinstance(url, str) or not url.strip():
            raise InputError(
                f'record entry {index} is missing a "url"; an evidence item '
                "without a source is not evidence"
            )
        relevance = item.get("relevance", 0.0)
        if isinstance(relevance, bool) or not isinstance(relevance, (int, float)):
            raise InputError(f'record entry {index} has a non-numeric "relevance": {relevance!r}')
        items.append(item)
    return items


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
    try:
        plan = load_plan_file(args.plan)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    plan.rounds = max(plan.rounds, args.round_num)

    if args.print_fetches and not args.record:
        sys.stdout.write(
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
        try:
            evidence = load_evidence(args.record, plan)
        except InputError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        added = record_evidence(plan, evidence)
        save_plan(plan, args.plan)
        sys.stdout.write(
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
