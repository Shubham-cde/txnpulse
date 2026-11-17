"""Load a period as table `txn`, run the rule SQL and save results to outputs/.

Usage: .venv\\Scripts\\python.exe src/run_rules.py --period train|test
"""

import argparse

from db import OUTPUT_DIR, SQL_DIR, connect, has_statements, load_period, run_named_queries, run_sql_file

FLAGS_SQL = SQL_DIR / "10_features_and_flags.sql"
RESULT_SQL_FILES = [SQL_DIR / "20_rule_performance.sql", SQL_DIR / "30_metrics.sql"]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", choices=["train", "test"], required=True)
    return parser.parse_args()


def is_written(sql_path):
    return sql_path.exists() and has_statements(sql_path.read_text(encoding="utf-8"))


def main():
    args = parse_args()
    con = connect()
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
    for sql_path in RESULT_SQL_FILES:
        if not is_written(sql_path):
            print(f"skipped: {sql_path.name} not written yet")
            continue
        results = run_named_queries(con, sql_path, out_dir)
        print(f"{sql_path.name}: wrote {len(results)} tables to {out_dir}")


if __name__ == "__main__":
    main()
