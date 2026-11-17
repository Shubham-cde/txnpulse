"""Build the alert-level feature table for ML alert prioritisation.

The model only ranks transactions that at least one ACTIVE rule alerted on
(rule set v2.1: R3, R4, R7). Features come from sql/60_ml_alert_features.sql.
"""

import sys
from pathlib import Path

# ml/ scripts reuse the pipeline helpers in src/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd  # noqa: E402

from db import SQL_DIR, connect, load_period, run_sql_file, split_named_queries  # noqa: E402

FEATURE_SQL = SQL_DIR / "60_ml_alert_features.sql"

ID_COLUMNS = ["trans_num", "card_id", "ts", "active_fired", "strongest_action_severity", "active_rules"]
LABEL_COLUMN = "is_fraud"
NUMERIC_FEATURES = [
    "amt", "amt_to_avg30", "txn_count_60m", "spend_24h", "hour_of_day", "distance_km",
    "first_visit", "rules_fired",
    "flag_r1", "flag_r2", "flag_r3", "flag_r4", "flag_r5", "flag_r6", "flag_r7",
]
CATEGORY_FEATURE = "category"

# Guard against accidental leakage: none of these may ever become a model input.
FORBIDDEN_FEATURES = {"is_fraud", "r8_risk_list_hit", "risk_list_tier", "risk_list_version", "card_id", "trans_num"}


def build_rule_tables(con):
    """Run sql/10 and the sql/20 preamble on an existing `txn` table. R8 (sql/15) is never run."""
    run_sql_file(con, SQL_DIR / "10_features_and_flags.sql")
    preamble, _ = split_named_queries((SQL_DIR / "20_rule_performance.sql").read_text(encoding="utf-8"))
    con.execute(preamble)


def load_txn_frame(con, frame):
    """Create `txn` from a small DataFrame (synthetic tests). Needs columns trans_num, ts,
    card_id, merchant, category, amt, is_fraud; other loader columns get neutral values."""
    con.register("txn_frame", frame)
    con.execute("""
        CREATE OR REPLACE TABLE txn AS
        SELECT trans_num, CAST(ts AS TIMESTAMP) AS ts, card_id, merchant, category,
               CAST(amt AS DOUBLE) AS amt, 'test city' AS city, 'TS' AS state, '00000' AS zip,
               40.0 AS lat, -75.0 AS long, CAST(1000 AS BIGINT) AS city_pop,
               40.1 AS merch_lat, -75.0 AS merch_long, CAST(0 AS BIGINT) AS unix_time,
               CAST(is_fraud AS INTEGER) AS is_fraud, TRUE AS is_scored
        FROM txn_frame
    """)
    con.unregister("txn_frame")


def all_row_features(con):
    """Feature rows for every scored transaction, alerted or not."""
    return con.sql(FEATURE_SQL.read_text(encoding="utf-8")).df()


def alerted_rows(features):
    return features[features["active_fired"] > 0].reset_index(drop=True)


def load_alert_features(period):
    return load_period_features(period)[0]


def load_period_features(period):
    """Alerted rows, plus total fraud value per day over ALL scored rows (alerted or not),
    so value@K can also be reported as a share of all fraud."""
    con = connect()
    load_period(con, period)
    build_rule_tables(con)
    rows = all_row_features(con)
    fraud = rows[rows["is_fraud"] == 1]
    daily_fraud_amt = fraud.groupby(fraud["ts"].dt.date)["amt"].sum()
    return alerted_rows(rows), daily_fraud_amt


def category_levels(train_features):
    """Category levels are fixed from training data, so test can't add columns."""
    return sorted(train_features[CATEGORY_FEATURE].unique())


def model_matrix(features, categories):
    """Numeric features plus one-hot category columns, in a fixed column order."""
    matrix = features[NUMERIC_FEATURES].astype(float).copy()
    for level in categories:
        matrix[f"category_{level}"] = (features[CATEGORY_FEATURE] == level).astype(float)
    leaked = FORBIDDEN_FEATURES.intersection(matrix.columns)
    if leaked:
        raise ValueError(f"forbidden columns in the model matrix: {sorted(leaked)}")
    return matrix
