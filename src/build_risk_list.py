"""Build the versioned R8 merchant risk list from the training file only.

Usage: .venv\\Scripts\\python.exe src/build_risk_list.py
Writes rules/risk_lists/merchant_risk_v1.csv.
"""

from db import CSV_BY_PERIOD, REPO_ROOT, SQL_DIR, connect, load_csv, run_named_queries

RISK_LIST_DIR = REPO_ROOT / "rules" / "risk_lists"


def main():
    con = connect()
    # Only fraudTrain is ever loaded here; the list must not see test labels.
    load_csv(con, CSV_BY_PERIOD["train"], "raw_train")
    results = run_named_queries(con, SQL_DIR / "45_build_risk_list.sql", RISK_LIST_DIR)
    built = RISK_LIST_DIR / "merchant_risk_list.csv"
    target = RISK_LIST_DIR / "merchant_risk_v1.csv"
    built.replace(target)
    risk_list = results["merchant_risk_list"]
    print(f"wrote {target}: {len(risk_list)} merchants "
          f"({(risk_list['tier'] == 'very_high').sum()} very_high, {(risk_list['tier'] == 'high').sum()} high)")


if __name__ == "__main__":
    main()
