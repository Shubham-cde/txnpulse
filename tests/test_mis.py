"""Tests for the Excel MIS (mis/build_mis.py) on a synthetic day; no Kaggle data needed.

openpyxl writes formulas but does not calculate them, so this file includes a small
evaluator for the formula patterns the MIS uses (COUNTIFS, SUMIFS, IFERROR division,
cell arithmetic). It recomputes every formula from the Raw sheet and compares it with
the Python check values written next to it.
"""

import re

import pandas as pd
import pytest
from openpyxl import load_workbook

from build_mis import RAW_COLUMNS, SHEETS, build_mis

N_ALERTS = 25


def synthetic_day():
    rows = []
    categories = ["shopping_net", "grocery_pos", "travel"]
    actions = ["HOLD_CONFIRM", "ALERT"]
    for i in range(N_ALERTS):
        rows.append({
            "alert_time": f"2020-12-24 {i % 24:02d}:15:00",
            "card": f"XXXX{1000 + i}",
            "category": categories[i % 3],
            "hour": i % 24,
            "amount": round(100.0 + 37.5 * i, 2),
            "rules_fired": "R3 R4" if i % 2 else "R7",
            "fired_r3": i % 2,
            "fired_r4": i % 2,
            "fired_r7": 1 - i % 2,
            "strongest_action": actions[i % 2 == 0],
            "model_score": round(1 - i / N_ALERTS, 4),
            "daily_rank": i + 1,
            "reason_codes": "HIGH_AMT LATE_NIGHT",
            "case_id": f"test_{i // 2}",
            "is_case_opening": int(i % 2 == 0),
            "is_fraud": int(i % 4 == 0),
        })
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def workbook(tmp_path_factory):
    path = tmp_path_factory.mktemp("mis") / "mis.xlsx"
    build_mis(synthetic_day(), "test", "2020-12-24", path)
    return load_workbook(path)


# ---- minimal formula evaluator for the patterns build_mis writes ----

def split_args(text):
    args, depth, quoted, current = [], 0, False, ""
    for ch in text:
        if ch == '"':
            quoted = not quoted
        if ch == "(" and not quoted:
            depth += 1
        if ch == ")" and not quoted:
            depth -= 1
        if ch == "," and depth == 0 and not quoted:
            args.append(current)
            current = ""
        else:
            current += ch
    args.append(current)
    return args


def column_values(raw, range_text):
    letter = re.match(r"Raw!\$([A-Z]+)\$2:\$[A-Z]+\$\d+", range_text).group(1)
    column = RAW_COLUMNS[ord(letter) - ord("A")]
    return list(raw[column])


def matches(value, criterion):
    criterion = criterion.strip('"')
    if criterion == "<>":
        return value not in (None, "")
    for op in ("<=", ">=", "<", ">"):
        if criterion.startswith(op):
            number = float(criterion[len(op):])
            return {"<=": value <= number, ">=": value >= number, "<": value < number, ">": value > number}[op]
    try:
        return float(value) == float(criterion)
    except (TypeError, ValueError):
        return str(value) == criterion


def evaluate(formula, sheet, raw):
    text = formula[1:] if formula.startswith("=") else formula
    if text.startswith("IFERROR("):
        inner = text[len("IFERROR("):text.rindex(",0)")]
        numerator, denominator = split_division(inner)
        bottom = evaluate(denominator, sheet, raw)
        return evaluate(numerator, sheet, raw) / bottom if bottom else 0
    if text.startswith(("COUNTIFS(", "SUMIFS(")):
        name, body = text.split("(", 1)
        args = split_args(body[:-1])
        sum_range = column_values(raw, args.pop(0)) if name == "SUMIFS" else None
        pairs = [(column_values(raw, args[i]), args[i + 1]) for i in range(0, len(args), 2)]
        keep = [all(matches(values[row], crit) for values, crit in pairs) for row in range(len(raw))]
        if name == "COUNTIFS":
            return sum(keep)
        return sum(v for v, k in zip(sum_range, keep) if k)
    if re.fullmatch(r"B\d+-B\d+", text):
        left, right = text.split("-")
        return evaluate(sheet[left].value, sheet, raw) - evaluate(sheet[right].value, sheet, raw)
    if re.fullmatch(r"[A-Z]\d+", text):
        return evaluate(sheet[text].value, sheet, raw)
    return float(text)


def split_division(text):
    depth = 0
    for i, ch in enumerate(text):
        depth += ch == "("
        depth -= ch == ")"
        if ch == "/" and depth == 0:
            return text[:i], text[i + 1:]
    raise ValueError(text)


def raw_frame(workbook):
    rows = list(workbook["Raw"].iter_rows(values_only=True))
    return pd.DataFrame(rows[1:], columns=rows[0])


# ---- tests ----

def test_sheet_names(workbook):
    assert workbook.sheetnames == SHEETS


def test_row_counts(workbook):
    assert workbook["Raw"].max_row == N_ALERTS + 1
    assert workbook["Top 20"].max_row == 20 + 1
    assert workbook["By hour"].max_row == 24 + 1
    assert workbook["By rule"].max_row == 3 + 1
    assert workbook["By category"].max_row == 3 + 1


def test_raw_is_a_pivot_ready_table(workbook):
    assert "RawAlerts" in workbook["Raw"].tables
    assert [c.value for c in workbook["Raw"][1]] == RAW_COLUMNS


def test_summary_values_are_formulas_on_raw(workbook):
    sheet = workbook["Summary"]
    for row in range(4, sheet.max_row + 1):
        value = sheet.cell(row=row, column=2).value
        assert isinstance(value, str) and value.startswith("="), f"Summary!B{row} is not a formula"
    countifs = [sheet.cell(row=r, column=2).value for r in range(4, sheet.max_row + 1)]
    assert any("COUNTIFS(Raw!" in f for f in countifs)
    assert any("SUMIFS(Raw!" in f for f in countifs)


def test_summary_formulas_match_python_checks(workbook):
    sheet, raw = workbook["Summary"], raw_frame(workbook)
    for row in range(4, sheet.max_row + 1):
        formula, check = sheet.cell(row=row, column=2).value, sheet.cell(row=row, column=3).value
        assert evaluate(formula, sheet, raw) == pytest.approx(check, abs=1e-4), sheet.cell(row=row, column=1).value


@pytest.mark.parametrize("name", ["By rule", "By category", "By hour"])
def test_breakdown_formulas_match_python_checks(workbook, name):
    sheet, raw = workbook[name], raw_frame(workbook)
    for row in range(2, sheet.max_row + 1):
        alerts_formula = sheet.cell(row=row, column=2).value
        assert alerts_formula.startswith("=COUNTIFS(Raw!")
        assert evaluate(alerts_formula, sheet, raw) == sheet.cell(row=row, column=6).value
