"""Load a period as table `txn`, run the rule SQL and save results to outputs/.

Usage: .venv\\Scripts\\python.exe src/run_rules.py --period train|test
"""

import argparse

from db import (
    OUTPUT_DIR, RISK_LIST_CSV, SQL_DIR, connect, has_statements, load_period, run_named_queries, run_sql_file,
)

FLAGS_SQL = SQL_DIR / "10_features_and_flags.sql"
# R8's list is built from train labels, so R8 is only ever scored on test.
TEST_ONLY_FLAGS_SQL = SQL_DIR / "15_r8_risk_list.sql"
RESULT_SQL_FILES = [
    SQL_DIR / "20_rule_performance.sql",
    SQL_DIR / "30_metrics.sql",
    SQL_DIR / "35_period_profile.sql",
]
# Threshold sweeps are only ever run on train, so nothing is tuned on test.
TRAIN_ONLY_SQL_FILES = [SQL_DIR / "40_sweeps_train.sql"]
TEST_ONLY_SQL_FILES = [SQL_DIR / "50_pvt_test.sql"]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", choices=["train", "test"], required=True)
    parser.add_argument(
        "--review-cost", type=float, default=5.0,
        help="assumed cost in USD to review one alert, used for net benefit",
    )
    return parser.parse_args()


def is_written(sql_path):
    return sql_path.exists() and has_statements(sql_path.read_text(encoding="utf-8"))


def main():
    args = parse_args()
    con = connect()
    con.execute(f"SET VARIABLE review_cost = {args.review_cost}")
    load_period(con, args.period)

    counts = con.execute(
        "SELECT COUNT(*) AS rows, SUM(CAST(is_scored AS INTEGER)) AS scored_rows FROM txn"
    ).fetchone()
    print(f"period={args.period}: txn has {counts[0]:,} rows, {counts[1]:,} scored")

    if not is_written(FLAGS_SQL):
        print(f"skipped: {FLAGS_SQL.name} not written yet")
        return
    run_sql_file(con, FLAGS_SQL)

    out_dir = OUTPUT_DIR / args.period
    if args.period == "test":
        run_named_queries(con, TEST_ONLY_FLAGS_SQL, out_dir, {"risk_list_csv": RISK_LIST_CSV.as_posix()})
        print(f"{TEST_ONLY_FLAGS_SQL.name}: R8 added from {RISK_LIST_CSV.name}")

    sql_files = RESULT_SQL_FILES + (TRAIN_ONLY_SQL_FILES if args.period == "train" else TEST_ONLY_SQL_FILES)
    for sql_path in sql_files:
        if not is_written(sql_path):
            print(f"skipped: {sql_path.name} not written yet")
            continue
        results = run_named_queries(con, sql_path, out_dir)
        print(f"{sql_path.name}: wrote {len(results)} tables to {out_dir}")


if __name__ == "__main__":
    main()
