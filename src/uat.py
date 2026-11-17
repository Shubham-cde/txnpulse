"""Run UAT cases from tests/uat_cases.csv through sql/10.

Each case is a small set of transactions sharing a test_id. One row is the
target; the case passes when the rule's flag on that row equals expected_hit.
"""

import csv

from db import REPO_ROOT, SQL_DIR, connect, run_sql_file

UAT_CASES_CSV = REPO_ROOT / "tests" / "uat_cases.csv"

RULE_COLUMNS = {
    "R1": "r1_velocity",
    "R2": "r2_amount_spike",
    "R3": "r3_late_night_high_value",
    "R4": "r4_risky_category_amount",
    "R5": "r5_distance_anomaly",
    "R6": "r6_new_merchant_high_amount",
    "R7": "r7_spend_burst_24h",
}

# Same column names and types as sql/00_load.sql produces, plus is_scored.
# Fields a case does not set get neutral defaults.
TXN_TABLE_SQL = """
CREATE OR REPLACE TABLE txn AS
SELECT
    trans_num,
    CAST(ts AS TIMESTAMP)       AS ts,
    card_id,
    merchant,
    category,
    CAST(amt AS DOUBLE)         AS amt,
    'test city'                 AS city,
    'TS'                        AS state,
    '00000'                     AS zip,
    CAST(lat AS DOUBLE)         AS lat,
    CAST(long AS DOUBLE)        AS long,
    CAST(1000 AS BIGINT)        AS city_pop,
    CAST(merch_lat AS DOUBLE)   AS merch_lat,
    CAST(merch_long AS DOUBLE)  AS merch_long,
    CAST(0 AS BIGINT)           AS unix_time,
    0                           AS is_fraud,
    TRUE                        AS is_scored
FROM case_rows
"""


def load_cases(path=UAT_CASES_CSV):
    """Return {test_id: [row dicts]} in file order."""
    cases = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cases.setdefault(row["test_id"], []).append(row)
    return cases


def target_row(rows):
    targets = [r for r in rows if r["is_target"] == "1"]
    if len(targets) != 1:
        raise ValueError(f"{rows[0]['test_id']}: expected exactly 1 target row, found {len(targets)}")
    return targets[0]


def parse_expected(value):
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    raise ValueError(f"expected_hit must be true or false, got {value!r}")


def run_case(rows):
    """Load the case's rows as `txn`, run sql/10 and return the target row's flag value."""
    target = target_row(rows)
    rule_column = RULE_COLUMNS[target["rule"]]

    con = connect()
    con.execute(
        "CREATE TABLE case_rows (trans_num VARCHAR, ts VARCHAR, card_id VARCHAR, merchant VARCHAR, "
        "category VARCHAR, amt VARCHAR, lat VARCHAR, long VARCHAR, merch_lat VARCHAR, merch_long VARCHAR)"
    )
    con.executemany(
        "INSERT INTO case_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            [r["trans_num"], r["ts"], r["card_id"], r["merchant"], r["category"], r["amt"],
             r["lat"], r["long"], r["merch_lat"], r["merch_long"]]
            for r in rows
        ],
    )
    con.execute(TXN_TABLE_SQL)
    run_sql_file(con, SQL_DIR / "10_features_and_flags.sql")

    result = con.execute(
        f"SELECT {rule_column} FROM flags WHERE trans_num = ?", [target["trans_num"]]
    ).fetchall()
    con.close()
    if len(result) != 1:
        raise ValueError(f"{target['test_id']}: target row returned {len(result)} rows from flags")
    return result[0][0]
