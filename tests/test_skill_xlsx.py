"""xlsx skill — load, eligibility, and create→inspect→edit round-trip."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agentos.skills.eligibility import EligibilityContext, check_eligibility
from agentos.skills.loader import SkillLoader

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "agentos" / "skills" / "bundled"
SCRIPTS = BUNDLED / "xlsx" / "scripts"


def _spec() -> object:
    return SkillLoader(bundled_dir=BUNDLED).get_by_name("xlsx")


def test_skill_loads() -> None:
    spec = _spec()
    assert spec is not None
    assert spec.name == "xlsx"
    assert spec.metadata is not None


def test_eligibility_with_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agentos.skills.eligibility.shutil.which",
        lambda name: "/usr/bin/python3" if name in {"python", "python3"} else None,
    )
    spec = _spec()
    assert spec is not None
    assert check_eligibility(spec, EligibilityContext.auto())


def test_round_trip_with_formula_and_merge(tmp_path: Path) -> None:
    sys.path.insert(0, str(SCRIPTS))
    try:
        import create_xlsx  # type: ignore[import-not-found]
        import edit_xlsx  # type: ignore[import-not-found]
        import inspect_xlsx  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    spec = {
        "sheets": [
            {
                "name": "Sales",
                "rows": [
                    ["Region", "Revenue"],
                    ["NA", 1_200_000],
                    ["EU", 850_000],
                    ["Total", "=SUM(B2:B3)"],
                ],
                "merged": [{"range": "A1:B1"}],
                "freeze": "A2",
            }
        ]
    }
    src = tmp_path / "book.xlsx"
    create_xlsx.build(spec).save(str(src))
    assert src.exists()

    inspected = inspect_xlsx.inspect(src, data_only=False)
    sheet = next(s for s in inspected["sheets"] if s["name"] == "Sales")
    assert sheet["max_row"] == 4
    assert sheet["max_col"] == 2
    assert any("A1:B1" in r for r in sheet["merged"])
    assert sheet["freeze"] == "A2"

    last_row = sheet["rows"][3]
    assert last_row[1]["type"] == "f"
    assert last_row[1]["value"] == "=SUM(B2:B3)"

    from openpyxl import load_workbook

    wb = load_workbook(str(src))
    edit_xlsx.apply_ops(
        wb,
        [
            {"op": "set_cell", "sheet": "Sales", "row": 2, "col": 1, "value": "Americas"},
            {"op": "rename_sheet", "old": "Sales", "new": "Q3"},
        ],
    )
    out = tmp_path / "out.xlsx"
    wb.save(str(out))

    re_inspected = inspect_xlsx.inspect(out, data_only=False)
    sheet_q3 = next(s for s in re_inspected["sheets"] if s["name"] == "Q3")
    assert sheet_q3["rows"][1][0]["value"] == "Americas"


def test_text_escapes_formula(tmp_path: Path) -> None:
    sys.path.insert(0, str(SCRIPTS))
    try:
        import create_xlsx  # type: ignore[import-not-found]
        import edit_xlsx  # type: ignore[import-not-found]
        import inspect_xlsx  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    src = tmp_path / "book.xlsx"
    create_xlsx.build({"sheets": [{"name": "S", "rows": [["a"]]}]}).save(str(src))

    from openpyxl import load_workbook

    wb = load_workbook(str(src))
    edit_xlsx.apply_ops(
        wb,
        [
            {
                "op": "set_cell",
                "sheet": "S",
                "row": 2,
                "col": 1,
                "value": "=hello",
                "as_text": True,
            },
        ],
    )
    out = tmp_path / "out.xlsx"
    wb.save(str(out))

    inspected = inspect_xlsx.inspect(out, data_only=False)
    sheet = inspected["sheets"][0]
    cell_value = sheet["rows"][1][0]["value"]
    assert isinstance(cell_value, str)
    assert cell_value.lstrip("'") == "=hello"


def _run_edit_xlsx_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    src: Path,
    ops: list[dict[str, object]],
    out: Path,
) -> dict[str, object]:
    """Invoke edit_xlsx's real CLI entry point (argv -> main()), not
    apply_ops() directly, so a save/reload through the same path the issue's
    exact reproduction used is what the regression actually exercises."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        import edit_xlsx  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    ops_path = out.with_name(out.stem + "-ops.json")
    ops_path.write_text(json.dumps(ops), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["edit_xlsx.py", str(src), str(ops_path), "--out", str(out)])
    capsys.readouterr()
    assert edit_xlsx.main() == 0
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(
    ("initial_value", "kind"),
    [
        ("old value", "text"),
        (42, "numeric"),
        ("=A1+A2", "formula"),
    ],
)
def test_set_cell_explicit_null_clears_the_cell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    initial_value: object,
    kind: str,
) -> None:
    """An explicit JSON null must clear the cell and report the edit as
    applied -- not silently leave the previous value in place while still
    exiting 0 with {"applied": 1} (#1260).

    openpyxl's own Worksheet.cell(..., value=...) only assigns when value is
    not None, so routing a null through that keyword is a no-op; this pins
    that edit_xlsx does not repeat the trap for any of the three cell kinds
    the issue reported failing. Verified the same way the issue's own
    reproduction did: reopen the saved output with openpyxl directly (not
    through inspect_xlsx, which omits an empty cell from its "rows" output
    entirely -- it would report nothing there whether the cell had cleared
    correctly or the whole sheet had gone missing).

    A second, never-touched cell keeps the sheet non-empty after the clear;
    a single-cell sheet's dimensions can otherwise shift once its only cell
    goes to None, which is a detail of how the sheet is inspected, not of
    whether the clear itself worked.
    """
    sys.path.insert(0, str(SCRIPTS))
    try:
        import create_xlsx  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    src = tmp_path / "input.xlsx"
    create_xlsx.build({"sheets": [{"name": "Sheet", "rows": [[initial_value, "anchor"]]}]}).save(
        str(src)
    )

    out = tmp_path / f"output-{kind}.xlsx"
    result = _run_edit_xlsx_cli(
        monkeypatch,
        capsys,
        src=src,
        ops=[{"op": "set_cell", "sheet": "Sheet", "row": 1, "col": 1, "value": None}],
        out=out,
    )

    assert result == {"applied": 1}
    from openpyxl import load_workbook

    reloaded = load_workbook(str(out), data_only=False)
    cell = reloaded["Sheet"].cell(row=1, column=1)
    assert cell.value is None, f"{kind} cell was not cleared: {cell.value!r}"
    assert reloaded["Sheet"].cell(row=1, column=2).value == "anchor"


def test_set_cell_missing_value_key_is_not_applied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A set_cell op with no "value" key at all must be skipped, not treated
    as a clear -- a malformed operation must never silently wipe a cell it
    named no value for."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        import create_xlsx  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    src = tmp_path / "input.xlsx"
    create_xlsx.build({"sheets": [{"name": "Sheet", "rows": [["old value"]]}]}).save(str(src))

    out = tmp_path / "output.xlsx"
    result = _run_edit_xlsx_cli(
        monkeypatch,
        capsys,
        src=src,
        ops=[{"op": "set_cell", "sheet": "Sheet", "row": 1, "col": 1}],
        out=out,
    )

    assert result == {"applied": 0}
    from openpyxl import load_workbook

    reloaded = load_workbook(str(out), data_only=False)
    assert reloaded["Sheet"].cell(row=1, column=1).value == "old value"


@pytest.mark.parametrize(
    ("value", "expected_after_reload"),
    [
        (0, 0),
        (False, False),
        # openpyxl does not round-trip a written "" distinctly from an
        # unwritten cell -- confirmed with plain openpyxl, no edit_xlsx
        # involved: writing "" and reloading reads back None regardless.
        # That is a pre-existing property of the format/library, unrelated
        # to this fix's null-clear semantics, so it is pinned as-is rather
        # than asserted to equal "".
        ("", None),
    ],
)
def test_set_cell_falsy_values_are_not_treated_as_clear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    value: object,
    expected_after_reload: object,
) -> None:
    """0 and False are ordinary values, not clears -- only a literal JSON
    null triggers clear semantics. applied must still read 1: the op was a
    genuine, deliberate write, not skipped like a missing "value" key."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        import create_xlsx  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    src = tmp_path / "input.xlsx"
    create_xlsx.build({"sheets": [{"name": "Sheet", "rows": [["old value"]]}]}).save(str(src))

    out = tmp_path / "output.xlsx"
    result = _run_edit_xlsx_cli(
        monkeypatch,
        capsys,
        src=src,
        ops=[{"op": "set_cell", "sheet": "Sheet", "row": 1, "col": 1, "value": value}],
        out=out,
    )

    assert result == {"applied": 1}
    from openpyxl import load_workbook

    reloaded = load_workbook(str(out), data_only=False)
    assert reloaded["Sheet"].cell(row=1, column=1).value == expected_after_reload


def test_inspect_xlsx_creates_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.path.insert(0, str(SCRIPTS))
    try:
        import create_xlsx  # type: ignore[import-not-found]
        import inspect_xlsx  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    src = tmp_path / "book.xlsx"
    create_xlsx.build({"sheets": [{"name": "S", "rows": [["a"]]}]}).save(str(src))

    out = tmp_path / "nested" / "dir" / "out.json"
    monkeypatch.setattr(sys, "argv", ["inspect_xlsx.py", str(src), "--out", str(out)])
    assert inspect_xlsx.main() == 0
    assert out.is_file()
