"""Issue #2328: deep-research dropped evidence silently and crashed on bad JSON.

``iterate.py`` read the evidence record with::

    raw = json.loads(args.record.read_text(encoding="utf-8"))
    evidence = raw if isinstance(raw, list) else []

so every non-list payload became "recorded nothing". It then saved the plan
anyway, printed ``{"added": 0, ...}`` and exited 0 — the caller was told the
round succeeded while its findings were gone. Passing a single evidence object,
the obvious thing to try, is the common way to hit it.

Anything that failed to parse — malformed JSON, a UTF-16 file — reached the
operator as a traceback instead of ``error: ...`` / exit 2, and the same was
true of the plan file in both ``iterate.py`` and ``compile.py``, where
``model_validate_json`` raises ``ValidationError`` for malformed JSON *and* for
JSON that does not match the plan schema.

The same defect lives one level down, inside a record that *is* a list, which
is where the issue's title applies just as well:

==========================================  ===============================
record entry                                before
==========================================  ===============================
``{"subquestion_id": "sq-01", ...}`` (typo) silently dropped, exit 0, added 0
``"just a string"``                         ``AttributeError`` traceback
``{"relevance": "high"}``                   ``ValueError`` traceback
``{"subquestion_id": "sq-001"}`` (no url)   accepted, source with empty url
``null``                                    ``AttributeError`` traceback
==========================================  ===============================

Every item is now checked before anything is written, so a bad record leaves
the plan byte-for-byte as it was.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "agentos" / "skills" / "bundled" / "deep-research" / "scripts"


def _scripts():
    sys.path.insert(0, str(SCRIPTS))
    try:
        for name in ("plan", "iterate", "compile"):
            sys.modules.pop(name, None)
        import compile as compile_script  # type: ignore[import-not-found]
        import iterate  # type: ignore[import-not-found]
        import plan as plan_script  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    return plan_script, iterate, compile_script


@pytest.fixture
def workspace(tmp_path: Path):
    """A valid plan on disk, plus a snapshot to prove it was not touched."""
    plan_script, iterate, compile_script = _scripts()
    plan = plan_script.Plan(
        question="does validation matter?",
        depth="overview",
        created_at="2026-01-01T00:00:00Z",
        subquestions=plan_script.make_subquestions("does validation matter?", "overview"),
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    return {
        "tmp": tmp_path,
        "plan_path": plan_path,
        "before": plan_path.read_bytes(),
        "ids": [sq.id for sq in plan.subquestions],
        "iterate": iterate,
        "compile": compile_script,
        "plan_script": plan_script,
    }


def run_iterate(workspace, argv: list[str], monkeypatch) -> int:
    monkeypatch.setattr(sys, "argv", ["iterate.py", *argv])
    return int(workspace["iterate"].main())


def record(workspace, payload: str) -> Path:
    path = workspace["tmp"] / "record.json"
    path.write_text(payload, encoding="utf-8")
    return path


# ── a record that is not a list ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("payload", "described"),
    [
        ('{"subquestion_id": "sq-001", "url": "https://x", "title": "t"}', "dict"),
        ("null", "NoneType"),
        ('"evidence"', "str"),
        ("42", "int"),
        ("true", "bool"),
    ],
    ids=["single-object", "null", "string", "int", "bool"],
)
def test_a_non_list_record_is_refused(
    workspace, monkeypatch, capsys, payload: str, described: str
) -> None:
    """The reported bug. A single evidence object is what a caller reaches for
    first, and it used to report success having recorded nothing."""
    path = record(workspace, payload)

    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "must be a JSON list of evidence items" in err
    assert described in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    "payload", ["not json", "{", "[1,", '{"unclosed": '], ids=["prose", "brace", "comma", "partial"]
)
def test_an_unparseable_record_exits_2(workspace, monkeypatch, capsys, payload: str) -> None:
    path = record(workspace, payload)

    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert code == 2
    assert "is not valid JSON" in capsys.readouterr().err


def test_a_utf16_record_exits_2(workspace, monkeypatch, capsys) -> None:
    """``read_text(encoding="utf-8")`` raises ``UnicodeDecodeError``, which the
    JSON guard alone does not catch."""
    path = workspace["tmp"] / "record.json"
    path.write_bytes("[]".encode("utf-16"))

    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert code == 2
    assert "Traceback" not in capsys.readouterr().err


# ── items inside a list that is well-formed ─────────────────────────────────


def test_an_unknown_subquestion_id_is_refused(workspace, monkeypatch, capsys) -> None:
    """The typo case, and the sharpest form of the reported bug.

    ``record_evidence`` did ``if sq_id not in by_id: continue`` — so ``sq-01``
    instead of ``sq-001`` meant the evidence vanished, ``added`` did not count
    it, and the run still exited 0.
    """
    path = record(workspace, json.dumps([{"subquestion_id": "sq-01", "url": "https://x"}]))

    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "unknown subquestion_id" in err
    assert "sq-01" in err
    assert workspace["ids"][0] in err, "the message should name the ids that do exist"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ('["just a string"]', "must be an object"),
        ("[null]", "must be an object"),
        ("[42]", "must be an object"),
        ("[[]]", "must be an object"),
        ('[{"url": "https://x"}]', 'missing a "subquestion_id"'),
        ('[{"subquestion_id": "", "url": "https://x"}]', 'missing a "subquestion_id"'),
        ('[{"subquestion_id": 1, "url": "https://x"}]', 'missing a "subquestion_id"'),
    ],
    ids=["string", "null", "int", "list", "no-id", "empty-id", "non-string-id"],
)
def test_a_malformed_entry_is_refused(
    workspace, monkeypatch, capsys, payload: str, expected: str
) -> None:
    path = record(workspace, payload)

    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert code == 2
    err = capsys.readouterr().err
    assert expected in err
    assert "Traceback" not in err


@pytest.mark.parametrize("url", [None, "", "   "], ids=["absent", "empty", "whitespace"])
def test_an_entry_without_a_url_is_refused(workspace, monkeypatch, capsys, url) -> None:
    """``str(item.get("url", ""))`` accepted this and wrote a source pointing
    nowhere — evidence that cannot be checked is not evidence."""
    item = {"subquestion_id": workspace["ids"][0]}
    if url is not None:
        item["url"] = url
    path = record(workspace, json.dumps([item]))

    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert code == 2
    assert 'missing a "url"' in capsys.readouterr().err


@pytest.mark.parametrize(
    "relevance", ["high", None, [], {}, True], ids=["string", "null", "list", "dict", "bool"]
)
def test_a_non_numeric_relevance_is_refused(workspace, monkeypatch, capsys, relevance) -> None:
    """``float(item.get("relevance", 0.0))`` raised ``ValueError`` as a
    traceback. ``True`` is rejected too: ``isinstance(True, int)`` is True, so
    a bool would otherwise slip through as 1.0."""
    path = record(
        workspace,
        json.dumps(
            [{"subquestion_id": workspace["ids"][0], "url": "https://x", "relevance": relevance}]
        ),
    )

    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert code == 2
    assert 'non-numeric "relevance"' in capsys.readouterr().err


def test_the_offending_entry_is_named_by_index(workspace, monkeypatch, capsys) -> None:
    """A twenty-item record is unfixable if the message does not say which
    item is wrong."""
    good = {"subquestion_id": workspace["ids"][0], "url": "https://ok"}
    items = [good, good, good, {"subquestion_id": workspace["ids"][0]}, good]
    path = record(workspace, json.dumps(items))

    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert code == 2
    assert "entry 3" in capsys.readouterr().err


# ── the plan is never half-written ──────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        '{"subquestion_id": "x", "url": "y"}',
        "null",
        "not json",
        '["just a string"]',
        '[{"subquestion_id": "sq-999", "url": "https://x"}]',
        '[{"subquestion_id": "sq-001"}]',
    ],
    ids=["non-list", "null", "unparseable", "bad-item", "unknown-id", "no-url"],
)
def test_a_rejected_record_leaves_the_plan_untouched(workspace, monkeypatch, payload: str) -> None:
    """Validate-then-apply, not apply-as-you-go.

    The old path saved the plan even when it had recorded nothing, so a failed
    round still rewrote the file it was supposed to be updating.
    """
    path = record(workspace, payload)

    run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert workspace["plan_path"].read_bytes() == workspace["before"]


def test_a_valid_entry_after_an_invalid_one_is_not_partially_applied(
    workspace, monkeypatch
) -> None:
    """The item that would have succeeded must not land either — a half-applied
    round is worse than a refused one, because the caller cannot retry safely.
    """
    items = [
        {"subquestion_id": workspace["ids"][0], "url": "https://good"},
        {"subquestion_id": "sq-999", "url": "https://orphan"},
    ]
    path = record(workspace, json.dumps(items))

    run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert workspace["plan_path"].read_bytes() == workspace["before"]


# ── the plan file itself, in both scripts ───────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    ["not json", '{"wrong": "schema"}', "null", "[]", "42"],
    ids=["unparseable", "wrong-schema", "null", "list", "int"],
)
def test_iterate_refuses_an_invalid_plan(workspace, monkeypatch, capsys, payload: str) -> None:
    bad = workspace["tmp"] / "bad_plan.json"
    bad.write_text(payload, encoding="utf-8")

    code = run_iterate(
        workspace, ["--plan", str(bad), "--round", "1", "--print-fetches"], monkeypatch
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "is not valid JSON or plan schema" in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    "payload",
    ["not json", '{"wrong": "schema"}', "null", "[]", "42"],
    ids=["unparseable", "wrong-schema", "null", "list", "int"],
)
def test_compile_refuses_an_invalid_plan(workspace, monkeypatch, capsys, payload: str) -> None:
    """``compile.py`` loads the plan with the same call and crashed the same
    way, so it needs the same guard."""
    bad = workspace["tmp"] / "bad_plan.json"
    bad.write_text(payload, encoding="utf-8")
    out = workspace["tmp"] / "report.md"
    monkeypatch.setattr(sys, "argv", ["compile.py", "--plan", str(bad), "--out", str(out)])

    code = int(workspace["compile"].main())

    assert code == 2
    assert "is not valid JSON or plan schema" in capsys.readouterr().err
    assert not out.exists(), "no report should be written from a plan that did not load"


def test_a_utf16_plan_exits_2(workspace, monkeypatch, capsys) -> None:
    bad = workspace["tmp"] / "bad_plan.json"
    bad.write_bytes('{"question": "x"}'.encode("utf-16"))

    code = run_iterate(
        workspace, ["--plan", str(bad), "--round", "1", "--print-fetches"], monkeypatch
    )

    assert code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_a_missing_plan_is_still_reported(workspace, monkeypatch, capsys) -> None:
    code = run_iterate(
        workspace,
        ["--plan", str(workspace["tmp"] / "nope.json"), "--round", "1", "--print-fetches"],
        monkeypatch,
    )

    assert code == 2
    assert "not found" in capsys.readouterr().err


# ── the working path is undisturbed ─────────────────────────────────────────


def test_a_valid_record_is_recorded_and_reported(workspace, monkeypatch, capsys) -> None:
    items = [
        {"subquestion_id": workspace["ids"][0], "url": "https://a", "title": "A", "relevance": 0.9},
        {"subquestion_id": workspace["ids"][1], "url": "https://b"},
    ]
    path = record(workspace, json.dumps(items))

    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["added"] == 2
    assert workspace["plan_path"].read_bytes() != workspace["before"]


def test_an_empty_record_list_is_accepted(workspace, monkeypatch, capsys) -> None:
    """``[]`` is a well-formed record for a round that found nothing — that is
    not an error, and must stay distinguishable from one."""
    path = record(workspace, "[]")

    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["added"] == 0


def test_optional_fields_stay_optional(workspace, monkeypatch, capsys) -> None:
    """Only ``subquestion_id`` and ``url`` are required; the rest default."""
    path = record(
        workspace, json.dumps([{"subquestion_id": workspace["ids"][0], "url": "https://only"}])
    )

    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["added"] == 1


@pytest.mark.parametrize("relevance", [0, 1, 0.5, -1], ids=["zero", "one", "float", "negative"])
def test_numeric_relevance_values_are_accepted(workspace, monkeypatch, capsys, relevance) -> None:
    path = record(
        workspace,
        json.dumps(
            [{"subquestion_id": workspace["ids"][0], "url": "https://x", "relevance": relevance}]
        ),
    )

    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--record", str(path)],
        monkeypatch,
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["added"] == 1


def test_print_fetches_still_works_on_a_valid_plan(workspace, monkeypatch, capsys) -> None:
    code = run_iterate(
        workspace,
        ["--plan", str(workspace["plan_path"]), "--round", "1", "--print-fetches"],
        monkeypatch,
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["round"] == 1
    assert len(payload["fetches"]) == len(workspace["ids"])
    assert workspace["plan_path"].read_bytes() == workspace["before"]
