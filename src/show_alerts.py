"""Print one day's alert queue for the active rules.

Usage: .venv\\Scripts\\python.exe src/show_alerts.py --period train|test --date YYYY-MM-DD [--top 20]

The queue is sorted the way an analyst would work it: strongest action first,
then highest amount. Only active rules (rule_catalogue in sql/20) raise alerts.
"""

import argparse
from datetime import date

import pandas as pd

from db import SQL_DIR, connect, load_period, run_sql_file, split_named_queries

QUEUE_SQL = """
WITH action_rank(action, severity) AS (
    VALUES ('ALERT', 1), ('STEP_UP', 2), ('HOLD_CONFIRM', 3), ('BLOCK', 4)
)
SELECT
    STRFTIME(ANY_VALUE(h.ts), '%H:%M:%S')                          AS time,
    'XXXX' || RIGHT(ANY_VALUE(h.card_id), 4)                       AS card,
    ANY_VALUE(f.category)                                          AS category,
    ROUND(ANY_VALUE(h.amt), 2)                                     AS amount,
    STRING_AGG(UPPER(SPLIT_PART(h.rule, '_', 1)), ' ' ORDER BY h.rule) AS rules_fired,
    ARG_MAX(c.action, ar.severity)                                 AS strongest_action,
    CASE WHEN ANY_VALUE(h.is_fraud) = 1 THEN 'yes' ELSE 'no' END   AS fraud,
    MAX(ar.severity)                                               AS severity
FROM rule_hits_long h
JOIN rule_catalogue c USING (rule)
JOIN action_rank ar ON ar.action = c.action
JOIN scored_flags f USING (trans_num)
WHERE h.hit AND h.status = 'active' AND CAST(h.ts AS DATE) = ?
GROUP BY h.trans_num
ORDER BY severity DESC, amount DESC
"""


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", choices=["train", "test"], required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="YYYY-MM-DD")
    parser.add_argument("--top", type=int, default=20, help="number of alerts to print (default 20)")
    return parser.parse_args()


def build_alert_tables(con, period):
    load_period(con, period)
    run_sql_file(con, SQL_DIR / "10_features_and_flags.sql")
    # Only the preamble of sql/20 is needed: rule_catalogue, scored_flags, rule_hits_long.
    preamble, _ = split_named_queries((SQL_DIR / "20_rule_performance.sql").read_text(encoding="utf-8"))
    con.execute(preamble)


def main():
    args = parse_args()
    con = connect()
    build_alert_tables(con, args.period)

    first_day, last_day = con.execute("SELECT MIN(ts)::DATE, MAX(ts)::DATE FROM scored_flags").fetchone()
    if not first_day <= args.date <= last_day:
        raise SystemExit(f"{args.date} is outside the {args.period} period ({first_day} to {last_day})")

    queue = con.execute(QUEUE_SQL, [args.date]).df().drop(columns="severity")
    total, fraud = len(queue), int((queue["fraud"] == "yes").sum())
    print(f"{args.period} {args.date}: {total} alerts from active rules, {fraud} fraud. "
          f"Showing top {min(args.top, total)} (strongest action, then amount).")
    if total:
        with pd.option_context("display.width", 200, "display.max_columns", None):
            print(queue.head(args.top).to_string(index=False))


if __name__ == "__main__":
    main()
