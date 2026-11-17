"""Run data-quality checks on both files and EDA on the training file.

Usage: .venv\\Scripts\\python.exe src/profile_data.py
Writes outputs/dq/*.csv and outputs/eda/*.csv.
"""

from db import CSV_BY_PERIOD, OUTPUT_DIR, SQL_DIR, connect, load_csv, run_named_queries


def main():
    con = connect()
    load_csv(con, CSV_BY_PERIOD["train"], "raw_train")
    load_csv(con, CSV_BY_PERIOD["test"], "raw_test")

    dq = run_named_queries(con, SQL_DIR / "02_dq_checks.sql", OUTPUT_DIR / "dq")
    print(f"DQ: wrote {len(dq)} tables to {OUTPUT_DIR / 'dq'}")

    # EDA only ever sees training rows; drop the test table so it cannot leak in.
    con.execute("DROP VIEW IF EXISTS raw_both")
    con.execute("DROP TABLE raw_test")
    eda = run_named_queries(con, SQL_DIR / "01_eda.sql", OUTPUT_DIR / "eda")
    print(f"EDA: wrote {len(eda)} tables to {OUTPUT_DIR / 'eda'}")


if __name__ == "__main__":
    main()
