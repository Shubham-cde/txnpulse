"""Run every UAT case and refresh the results table in reports/uat_report.md.

Usage: .venv\\Scripts\\python.exe src/run_uat.py
Also writes outputs/uat/uat_results.csv. Only the text between the
results markers in the report is replaced; the rest is written by hand.
"""

import csv
from datetime import date

from db import OUTPUT_DIR, REPO_ROOT
from uat import load_cases, parse_expected, run_case, target_row

REPORT = REPO_ROOT / "reports" / "uat_report.md"
START_MARKER = "<!-- results:start -->"
END_MARKER = "<!-- results:end -->"


def run_all_cases():
    results = []
    for test_id, rows in sorted(load_cases().items()):
        target = target_row(rows)
        expected = parse_expected(target["expected_hit"])
        actual = run_case(rows)
        results.append({
            "test_id": test_id,
            "rule": target["rule"],
            "description": target["description"],
            "rows": len(rows),
            "expected_hit": expected,
            "actual_hit": actual,
            "result": "PASS" if actual is expected else "FAIL",
        })
    return results


def write_csv(results):
    out_dir = OUTPUT_DIR / "uat"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "uat_results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)


def results_markdown(results):
    passed = sum(r["result"] == "PASS" for r in results)
    lines = [
        f"Run on {date.today().isoformat()}: {passed} of {len(results)} cases passed.",
        "",
        "| Test ID | Rule | Scenario | Rows | Expected | Actual | Result |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['test_id']} | {r['rule']} | {r['description']} | {r['rows']} | "
            f"{'alert' if r['expected_hit'] else 'no alert'} | "
            f"{'alert' if r['actual_hit'] else ('no alert' if r['actual_hit'] is False else 'NULL')} | "
            f"{r['result']} |"
        )
    return "\n".join(lines)


def refresh_report(results):
    text = REPORT.read_text(encoding="utf-8")
    start = text.index(START_MARKER) + len(START_MARKER)
    end = text.index(END_MARKER)
    REPORT.write_text(text[:start] + "\n" + results_markdown(results) + "\n" + text[end:], encoding="utf-8")


def main():
    results = run_all_cases()
    write_csv(results)
    refresh_report(results)
    failed = [r["test_id"] for r in results if r["result"] == "FAIL"]
    print(f"{len(results) - len(failed)} of {len(results)} passed" + (f"; failed: {failed}" if failed else ""))


if __name__ == "__main__":
    main()
