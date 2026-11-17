"""Daily Excel MIS for one day's alert queue (rule set v2.1, model v1).

Usage: .venv\\Scripts\\python.exe mis/build_mis.py --period test --date 2020-12-24 [--out FILE]
Reads dashboards/extracts/fact_alerts.csv (built by dashboards/build_extracts.py).

Sheets:
  Summary      key figures as COUNTIFS/SUMIFS formulas on the Raw sheet, each next to a
               value computed in Python and an OK/CHECK cell, so the formulas can be verified
  By rule      alerts, fraud alerts and precision per active rule (formulas)
  By category  the same per merchant category (formulas)
  By hour      the same per hour of day (formulas)
  Top 20       the 20 highest model scores of the day (values)
  Raw          every alert of the day as an Excel table, ready for a pivot table
  Notes        definitions
"""

import argparse
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

ROOT = Path(__file__).resolve().parent.parent
FACT_ALERTS = ROOT / "dashboards" / "extracts" / "fact_alerts.csv"
DEFAULT_OUT_DIR = ROOT / "outputs" / "mis"
ALERT_BUDGET_PER_DAY = 50
ACTIVE_RULES = [("R3", "fired_r3", "Late-night high value"), ("R4", "fired_r4", "Risky category + amount"),
                ("R7", "fired_r7", "Spend burst (48 h)")]
RAW_COLUMNS = ["alert_time", "card", "category", "hour", "amount", "rules_fired", "fired_r3", "fired_r4",
               "fired_r7", "strongest_action", "model_score", "daily_rank", "reason_codes", "case_id",
               "is_case_opening", "is_fraud"]
SHEETS = ["Summary", "By rule", "By category", "By hour", "Top 20", "Raw", "Notes"]

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="2A78D6")
TITLE_FONT = Font(bold=True, size=13)


def raw_range(day_alerts, column):
    """Absolute range on the Raw sheet for one column, e.g. Raw!$E$2:$E$41."""
    letter = get_column_letter(RAW_COLUMNS.index(column) + 1)
    last_row = max(len(day_alerts), 1) + 1
    return f"Raw!${letter}$2:${letter}${last_row}"


def style_header(sheet, row, columns):
    for col, name in enumerate(columns, start=1):
        cell = sheet.cell(row=row, column=col, value=name)
        cell.font, cell.fill = HEADER_FONT, HEADER_FILL
        cell.alignment = Alignment(horizontal="center")


def write_raw(book, day_alerts):
    sheet = book.create_sheet("Raw")
    style_header(sheet, 1, RAW_COLUMNS)
    for row in day_alerts[RAW_COLUMNS].itertuples(index=False):
        sheet.append(list(row))
    last_row = len(day_alerts) + 1
    if len(day_alerts):
        table = Table(displayName="RawAlerts", ref=f"A1:{get_column_letter(len(RAW_COLUMNS))}{last_row}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        sheet.add_table(table)
    sheet.freeze_panes = "A2"
    for col in range(1, len(RAW_COLUMNS) + 1):
        sheet.column_dimensions[get_column_letter(col)].width = 14
    sheet.column_dimensions["M"].width = 48


def summary_rows(day_alerts):
    """(label, formula, python value, number format)."""
    r = lambda column: raw_range(day_alerts, column)  # noqa: E731
    alerts = len(day_alerts)
    fraud = int(day_alerts["is_fraud"].sum())
    fraud_value = round(float(day_alerts.loc[day_alerts["is_fraud"] == 1, "amount"].sum()), 2)
    top10 = day_alerts[day_alerts["daily_rank"] <= 10]
    return [
        ("Alerts (active rules)", f'=COUNTIFS({r("alert_time")},"<>")', alerts, "0"),
        ("Cases opened", f'=COUNTIFS({r("is_case_opening")},1)', int(day_alerts["is_case_opening"].sum()), "0"),
        ("HOLD_CONFIRM alerts (always worked)", f'=COUNTIFS({r("strongest_action")},"HOLD_CONFIRM")',
         int((day_alerts["strongest_action"] == "HOLD_CONFIRM").sum()), "0"),
        ("ALERT-only alerts", f'=COUNTIFS({r("strongest_action")},"ALERT")',
         int((day_alerts["strongest_action"] == "ALERT").sum()), "0"),
        ("Alert budget per day", f"={ALERT_BUDGET_PER_DAY}", ALERT_BUDGET_PER_DAY, "0"),
        ("Alerts over (+) or under (-) budget", f"=B4-B8", alerts - ALERT_BUDGET_PER_DAY, "0"),
        ("Fraud alerts (confirmed label)", f'=COUNTIFS({r("is_fraud")},1)', fraud, "0"),
        ("Precision", "=IFERROR(B10/B4,0)", round(fraud / alerts, 4) if alerts else 0, "0.00%"),
        ("Total amount alerted", f'=SUMIFS({r("amount")},{r("amount")},">0")',
         round(float(day_alerts["amount"].sum()), 2), "#,##0.00"),
        ("Fraud amount alerted", f'=SUMIFS({r("amount")},{r("is_fraud")},1)', fraud_value, "#,##0.00"),
        ("Precision of model top 10",
         f'=IFERROR(COUNTIFS({r("daily_rank")},"<=10",{r("is_fraud")},1)/COUNTIFS({r("daily_rank")},"<=10"),0)',
         round(float(top10["is_fraud"].mean()), 4) if len(top10) else 0, "0.00%"),
    ]


def write_summary(book, day_alerts, period, date):
    sheet = book.active
    sheet.title = "Summary"
    sheet["A1"] = f"TxnPulse daily MIS: {period} period, {date}"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = "Rule set v2.1 (active R3, R4, R7); queue order from ML model v1. Formulas read the Raw sheet."
    style_header(sheet, 3, ["Measure", "Value (formula)", "Python check", "Match"])
    for row_number, (label, formula, value, number_format) in enumerate(summary_rows(day_alerts), start=4):
        sheet.cell(row=row_number, column=1, value=label)
        sheet.cell(row=row_number, column=2, value=formula).number_format = number_format
        sheet.cell(row=row_number, column=3, value=value).number_format = number_format
        sheet.cell(row=row_number, column=4, value=f'=IF(ROUND(B{row_number},4)=ROUND(C{row_number},4),"OK","CHECK")')
    sheet.column_dimensions["A"].width = 38
    for col in "BCD":
        sheet.column_dimensions[col].width = 18


def write_breakdown(book, day_alerts, name, key_label, keys):
    """keys: list of (key value shown, criteria pieces for COUNTIFS/SUMIFS, python mask)."""
    sheet = book.create_sheet(name)
    columns = [key_label, "Alerts", "Fraud alerts", "Precision", "Fraud amount", "Python check: alerts"]
    style_header(sheet, 1, columns)
    fraud_range, amount_range = raw_range(day_alerts, "is_fraud"), raw_range(day_alerts, "amount")
    for row_number, (key, criteria, mask) in enumerate(keys, start=2):
        sheet.cell(row=row_number, column=1, value=key)
        sheet.cell(row=row_number, column=2, value=f"=COUNTIFS({criteria})")
        sheet.cell(row=row_number, column=3, value=f"=COUNTIFS({criteria},{fraud_range},1)")
        sheet.cell(row=row_number, column=4, value=f"=IFERROR(C{row_number}/B{row_number},0)").number_format = "0.00%"
        sheet.cell(row=row_number, column=5, value=f"=SUMIFS({amount_range},{criteria},{fraud_range},1)").number_format = "#,##0.00"
        sheet.cell(row=row_number, column=6, value=int(mask.sum()))
    for col in range(1, len(columns) + 1):
        sheet.column_dimensions[get_column_letter(col)].width = 22


def write_top20(book, day_alerts):
    sheet = book.create_sheet("Top 20")
    columns = ["daily_rank", "alert_time", "card", "category", "amount", "rules_fired", "strongest_action",
               "model_score", "reason_codes", "is_fraud"]
    style_header(sheet, 1, columns)
    for row in day_alerts.sort_values("daily_rank").head(20)[columns].itertuples(index=False):
        sheet.append(list(row))
    for col in range(1, len(columns) + 1):
        sheet.column_dimensions[get_column_letter(col)].width = 14
    sheet.column_dimensions["I"].width = 48


def write_notes(book):
    sheet = book.create_sheet("Notes")
    notes = [
        "Definitions",
        "Alert: a transaction on which at least one active rule (R3, R4, R7 in rule set v2.1) fired.",
        "Case opened: an alert that opens a case; later alerts on the same card within 24 hours join that case.",
        "HOLD_CONFIRM alerts are always worked regardless of model score (operating model).",
        "model_score / daily_rank: ML model v1 orders the queue; it never removes an alert. Rank 1 = review first.",
        "is_fraud: the confirmed label, known only later (chargebacks). Shown here to back-test the queue.",
        "Precision = fraud alerts / alerts. Fraud amount alerted counts only fraud alerts.",
        "Card numbers are masked to the last 4 digits.",
        "The 'Python check' columns hold the same figures computed outside Excel; 'Match' shows OK when the formula agrees.",
    ]
    for row_number, text in enumerate(notes, start=1):
        sheet.cell(row=row_number, column=1, value=text)
    sheet["A1"].font = TITLE_FONT
    sheet.column_dimensions["A"].width = 120


def build_mis(day_alerts, period, date, out_path):
    day_alerts = day_alerts.sort_values("daily_rank").reset_index(drop=True)
    book = Workbook()
    write_summary(book, day_alerts, period, date)

    rule_keys = [(f"{rule_id} {name}", f'{raw_range(day_alerts, column)},1', day_alerts[column] == 1)
                 for rule_id, column, name in ACTIVE_RULES]
    write_breakdown(book, day_alerts, "By rule", "Rule", rule_keys)
    categories = sorted(day_alerts["category"].unique())
    category_keys = [(c, f'{raw_range(day_alerts, "category")},"{c}"', day_alerts["category"] == c) for c in categories]
    write_breakdown(book, day_alerts, "By category", "Category", category_keys)
    hour_keys = [(h, f'{raw_range(day_alerts, "hour")},{h}', day_alerts["hour"] == h) for h in range(24)]
    write_breakdown(book, day_alerts, "By hour", "Hour", hour_keys)

    write_top20(book, day_alerts)
    write_raw(book, day_alerts)
    write_notes(book)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    book.save(out_path)
    return out_path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", choices=["train", "test"], required=True)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--out", help="output .xlsx (default outputs/mis/txnpulse_mis_<period>_<date>.xlsx)")
    return parser.parse_args()


def main():
    args = parse_args()
    if not FACT_ALERTS.exists():
        raise SystemExit("dashboards/extracts/fact_alerts.csv not found: run dashboards/build_extracts.py first")
    alerts = pd.read_csv(FACT_ALERTS)
    period_alerts = alerts[alerts["period"] == args.period]
    day_alerts = period_alerts[period_alerts["alert_date"] == args.date]
    if day_alerts.empty:
        first, last = period_alerts["alert_date"].min(), period_alerts["alert_date"].max()
        raise SystemExit(f"no alerts for {args.date} in the {args.period} period ({first} to {last})")
    out = args.out or DEFAULT_OUT_DIR / f"txnpulse_mis_{args.period}_{args.date}.xlsx"
    path = build_mis(day_alerts, args.period, args.date, out)
    print(f"wrote {path}: {len(day_alerts)} alerts, {int(day_alerts['is_fraud'].sum())} fraud")


if __name__ == "__main__":
    main()
