"""Build the Power BI star-schema extracts in dashboards/extracts/.

Usage: .venv\\Scripts\\python.exe dashboards/build_extracts.py   (after ml/train_ranker.py)

Rule set v2.1, ML model v1 (outputs/ml/model.pkl). Both periods are built with
the same SQL as the reports, so every number matches outputs/train and outputs/test.

Tables:
  fact_alerts        one row per alert from the v2.1 active set (R3, R4, R7)
  fact_daily_rule    per date per active or shadow rule
  agg_hour_category  per period, hour and category, from ALL transactions
  dim_rule           one row per rule R1-R8
  dim_date           one row per date and period (2020-06-21 is in both periods)
  dim_period         train / test, so one period slicer filters every table
Also writes expected_values.csv: the key numbers a correct Power BI build must show.
"""

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ml"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from db import OUTPUT_DIR, RISK_LIST_CSV, SQL_DIR, connect, fill_placeholders, load_period, split_named_queries  # noqa: E402
from explain import shap_values, top_reason_codes  # noqa: E402
from features import all_row_features, alerted_rows, build_rule_tables, model_matrix  # noqa: E402
from ranking import assign_cases  # noqa: E402

EXTRACT_DIR = Path(__file__).resolve().parent / "extracts"
RULE_SET_VERSION = "v2.1"
ACTION_BY_SEVERITY = {1: "ALERT", 2: "STEP_UP", 3: "HOLD_CONFIRM", 4: "BLOCK"}
DIM_RULE = pd.DataFrame([
    ("R1", "r1_velocity", "Card velocity", "1.1"),
    ("R2", "r2_amount_spike", "Amount spike", "1.0"),
    ("R3", "r3_late_night_high_value", "Late-night high value", "2.0"),
    ("R4", "r4_risky_category_amount", "Risky category + amount", "2.0"),
    ("R5", "r5_distance_anomaly", "Distance anomaly", "1.0"),
    ("R6", "r6_new_merchant_high_amount", "New merchant + high amount", "2.0"),
    ("R7", "r7_spend_burst", "Spend burst (48 h)", "2.0"),
    ("R8", "r8_risk_list_hit", "Risk-list hit", "1.0"),
], columns=["rule_id", "rule_column", "rule_name", "logic_version"])


def run_preamble(con, sql_file, params=None):
    preamble, _ = split_named_queries(fill_placeholders((SQL_DIR / sql_file).read_text(encoding="utf-8"), params))
    con.execute(preamble)


def period_connection(period):
    """Same table build as run_rules.py: sql/10, R8 on test only, sql/20 and sql/30 preambles."""
    con = connect()
    load_period(con, period)
    build_rule_tables(con)
    if period == "test":
        # build_rule_tables ran sql/20 without R8; rerun it after adding R8 so shadow R8 is counted.
        run_preamble(con, "15_r8_risk_list.sql", {"risk_list_csv": RISK_LIST_CSV.as_posix()})
        run_preamble(con, "20_rule_performance.sql")
    run_preamble(con, "30_metrics.sql")
    return con


def date_key(period, dates):
    return period + "_" + pd.to_datetime(dates).dt.strftime("%Y-%m-%d")


def alerts_for(con, period, saved):
    alerts = alerted_rows(all_row_features(con))
    matrix = model_matrix(alerts, saved["categories"])
    alerts["model_score"] = saved["model"].predict_proba(matrix)[:, 1]
    reasons = top_reason_codes(shap_values(saved["model"], matrix), alerts)
    alerts["reason_codes"] = reasons.map(lambda r: " ".join(code for code, _ in r))
    alerts["case_number"] = assign_cases(alerts)
    first_in_case = alerts.sort_values(["ts", "trans_num"]).groupby("case_number").head(1).index
    day = alerts["ts"].dt.date
    return pd.DataFrame({
        "alert_id": alerts["trans_num"],
        "date_key": date_key(period, alerts["ts"]),
        "alert_time": alerts["ts"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        "alert_date": alerts["ts"].dt.strftime("%Y-%m-%d"),
        "period": period,
        "card": "XXXX" + alerts["card_id"].str[-4:],
        "category": alerts["category"],
        "hour": alerts["hour_of_day"],
        "amount": alerts["amt"].round(2),
        "rules_fired": alerts["active_rules"],
        "active_rules_count": alerts["active_fired"],
        "fired_r3": alerts["flag_r3"],
        "fired_r4": alerts["flag_r4"],
        "fired_r7": alerts["flag_r7"],
        "strongest_action": alerts["strongest_action_severity"].map(ACTION_BY_SEVERITY),
        "model_score": alerts["model_score"].round(4),
        # Train scores are in-sample: model v1 was fitted on these alerts.
        "score_in_sample": period == "train",
        "daily_rank": alerts.groupby(day)["model_score"].rank(ascending=False, method="first").astype(int),
        "reason_codes": alerts["reason_codes"],
        "case_id": period + "_" + alerts["case_number"].astype(int).astype(str),
        "is_case_opening": alerts.index.isin(first_in_case).astype(int),
        "is_fraud": alerts["is_fraud"],
    })


def daily_rule_for(con, period):
    shown = con.execute("SELECT rule FROM rule_catalogue WHERE status IN ('active', 'shadow')").df()["rule"].tolist()
    alerts = con.execute("""
        SELECT CAST(ts AS DATE) AS date, rule, COUNT(*) AS alerts, SUM(is_fraud) AS fraud_alerts,
               COALESCE(SUM(amt) FILTER (WHERE is_fraud = 1), 0) AS fraud_value_caught
        FROM alerts_long GROUP BY ALL
    """).df()
    cases = con.execute("""
        SELECT CAST(case_start AS DATE) AS date, rule, COUNT(DISTINCT (card_id, case_start)) AS cases
        FROM alert_cases GROUP BY ALL
    """).df()
    totals = con.execute("SELECT CAST(ts AS DATE) AS date, COUNT(*) AS day_transactions FROM scored_flags GROUP BY ALL").df()
    daily = alerts.merge(cases, on=["date", "rule"], how="outer").fillna({"alerts": 0, "fraud_alerts": 0,
                                                                         "fraud_value_caught": 0, "cases": 0})
    daily = daily[daily["rule"].isin(shown)].merge(totals, on="date", how="left")
    daily = daily.merge(DIM_RULE[["rule_id", "rule_column"]], left_on="rule", right_on="rule_column")
    daily["date_key"] = date_key(period, daily["date"])
    daily["period"] = period
    columns = ["date_key", "period", "rule_id", "alerts", "cases", "fraud_alerts", "fraud_value_caught", "day_transactions"]
    out = daily[columns].copy()
    for column in ("alerts", "cases", "fraud_alerts", "day_transactions"):
        out[column] = out[column].astype(int)
    out["fraud_value_caught"] = out["fraud_value_caught"].round(2)
    return out.sort_values(["date_key", "rule_id"]).reset_index(drop=True)


def hour_category_for(con, period):
    agg = con.execute("""
        SELECT hour_of_day AS hour, category, COUNT(*) AS transactions, CAST(SUM(is_fraud) AS BIGINT) AS fraud_transactions,
               ROUND(COALESCE(SUM(amt) FILTER (WHERE is_fraud = 1), 0), 2) AS fraud_value
        FROM scored_flags GROUP BY ALL ORDER BY hour, category
    """).df()
    agg.insert(0, "period", period)
    return agg


def dates_for(con, period):
    dates = con.execute("""
        SELECT CAST(ts AS DATE) AS date, COUNT(*) AS day_transactions, SUM(is_fraud) AS day_fraud_transactions,
               ROUND(COALESCE(SUM(amt) FILTER (WHERE is_fraud = 1), 0), 2) AS day_fraud_value
        FROM scored_flags GROUP BY ALL ORDER BY date
    """).df()
    dates["date"] = pd.to_datetime(dates["date"])
    return pd.DataFrame({
        "date_key": date_key(period, dates["date"]),
        "date": dates["date"].dt.strftime("%Y-%m-%d"),
        "month": dates["date"].dt.strftime("%Y-%m"),
        "weekday": dates["date"].dt.day_name(),
        "weekday_number": dates["date"].dt.day_of_week + 1,
        "period": period,
        "is_december": (dates["date"].dt.month == 12).astype(int),
        "day_transactions": dates["day_transactions"].astype(int),
        "day_fraud_transactions": dates["day_fraud_transactions"].astype(int),
        "day_fraud_value": dates["day_fraud_value"],
    })


def dim_rule(con):
    catalogue = con.execute("SELECT rule, status, action FROM rule_catalogue").df()
    rules = DIM_RULE.merge(catalogue, left_on="rule_column", right_on="rule", how="left").drop(columns="rule")
    rules["rule_set_version"] = RULE_SET_VERSION
    return rules[["rule_id", "rule_name", "status", "action", "logic_version", "rule_set_version", "rule_column"]]


def expected_values(fact_alerts, fact_daily_rule, dim_date):
    """The numbers a correct Power BI build must show, computed the same way as the DAX."""
    rows = []
    for period in ("train", "test"):
        a = fact_alerts[fact_alerts["period"] == period]
        d = dim_date[dim_date["period"] == period]
        days = len(d)
        fraud = a["is_fraud"].sum()
        rows += [
            (period, "Active set", "Alerts", len(a)),
            (period, "Active set", "Cases", int(a["is_case_opening"].sum())),
            (period, "Active set", "Alerts per day", round(len(a) / days, 2)),
            (period, "Active set", "Cases per day", round(a["is_case_opening"].sum() / days, 2)),
            (period, "Active set", "Precision %", round(100 * fraud / len(a), 2)),
            (period, "Active set", "FP ratio", round((len(a) - fraud) / fraud, 2)),
            (period, "Active set", "Recall %", round(100 * fraud / d["day_fraud_transactions"].sum(), 2)),
            (period, "Active set", "Value detection %",
             round(100 * a.loc[a["is_fraud"] == 1, "amount"].sum() / d["day_fraud_value"].sum(), 2)),
        ]
        for k in (10, 20, 30):
            top = a[a["daily_rank"] <= k]
            rows.append((period, "Active set", f"Precision@{k} %", round(100 * top["is_fraud"].mean(), 2)))
        r = fact_daily_rule[fact_daily_rule["period"] == period].groupby("rule_id").sum(numeric_only=True)
        for rule_id, row in r.iterrows():
            rows += [
                (period, rule_id, "Alerts", int(row["alerts"])),
                (period, rule_id, "Alerts per day", round(row["alerts"] / days, 2)),
                (period, rule_id, "Precision %", round(100 * row["fraud_alerts"] / row["alerts"], 2)),
                (period, rule_id, "Recall %", round(100 * row["fraud_alerts"] / d["day_fraud_transactions"].sum(), 2)),
            ]
        rows.append((period, "Days", "Days in period", days))
    return pd.DataFrame(rows, columns=["period", "scope", "measure", "expected_value"])


def main():
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "ml" / "model.pkl", "rb") as f:
        saved = pickle.load(f)
    tables = {name: [] for name in ("fact_alerts", "fact_daily_rule", "agg_hour_category", "dim_date")}
    for period in ("train", "test"):
        con = period_connection(period)
        tables["fact_alerts"].append(alerts_for(con, period, saved))
        tables["fact_daily_rule"].append(daily_rule_for(con, period))
        tables["agg_hour_category"].append(hour_category_for(con, period))
        tables["dim_date"].append(dates_for(con, period))
        rules = dim_rule(con)
    tables = {name: pd.concat(parts, ignore_index=True) for name, parts in tables.items()}
    tables["dim_rule"] = rules
    tables["dim_period"] = pd.DataFrame({"period": ["train", "test"], "period_order": [1, 2],
                                         "period_label": ["Train 2019-01-01 to 2020-06-21", "Test 2020-06-21 to 2020-12-31"]})
    for name, table in tables.items():
        table.to_csv(EXTRACT_DIR / f"{name}.csv", index=False)
        size_kb = (EXTRACT_DIR / f"{name}.csv").stat().st_size / 1024
        print(f"{name}: {len(table):,} rows, {size_kb:,.0f} KB")
    expected = expected_values(tables["fact_alerts"], tables["fact_daily_rule"], tables["dim_date"])
    expected.to_csv(EXTRACT_DIR / "expected_values.csv", index=False)
    print(f"expected_values: {len(expected)} rows")


if __name__ == "__main__":
    main()
