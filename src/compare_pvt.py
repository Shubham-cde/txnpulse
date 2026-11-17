"""Compare the frozen rule set on train and test for post-deployment validation.

Usage: .venv\\Scripts\\python.exe src/compare_pvt.py
Needs outputs/train and outputs/test from run_rules.py. Writes
outputs/pvt/pvt_rule_comparison.csv.

Precision depends on the fraud base rate, so it is not compared on its own.
For each rule, expected_test_precision is the precision the rule would have
on test if it kept its train recall and its train genuine alert rate (the
share of genuine transactions it alerts on). Actual precision close to that
figure means the drop is explained by the lower base rate, not by the rule.
"""

import pandas as pd

from db import OUTPUT_DIR

COMBINED = ["any_active", "any_active_or_shadow"]


def period_metrics(period):
    perf = pd.read_csv(OUTPUT_DIR / period / "rule_performance.csv")
    value = pd.read_csv(OUTPUT_DIR / period / "value_detection.csv")
    cards = pd.read_csv(OUTPUT_DIR / period / "card_detection.csv")
    cases = pd.read_csv(OUTPUT_DIR / period / "case_volume.csv")
    profile = pd.read_csv(OUTPUT_DIR / period / "profile_period.csv").iloc[0]

    df = (perf[["rule", "status", "alerts", "alerts_per_day", "fraud_alerts", "precision_pct", "txn_recall_pct"]]
          .merge(value[["rule", "value_detection_pct", "net_benefit"]], on="rule", how="left")
          .merge(cards[["rule", "card_detection_pct"]], on="rule", how="left")
          .merge(cases[["rule", "cases_per_day"]], on="rule", how="left"))
    df["genuine_alert_rate_pct"] = 100 * (df["alerts"] - df["fraud_alerts"]) / profile["genuine_txns"]
    return df, profile


def expected_precision(recall_pct, genuine_alert_rate_pct, profile):
    expected_fraud_alerts = recall_pct / 100 * profile["fraud_txns"]
    expected_genuine_alerts = genuine_alert_rate_pct / 100 * profile["genuine_txns"]
    total = expected_fraud_alerts + expected_genuine_alerts
    return 100 * expected_fraud_alerts / total if total else float("nan")


def compare():
    train, _ = period_metrics("train")
    test, test_profile = period_metrics("test")
    merged = train.merge(test, on="rule", how="outer", suffixes=("_train", "_test"))
    merged["status"] = merged["status_test"].fillna(merged["status_train"])
    merged["expected_test_precision_pct"] = [
        expected_precision(r, g, test_profile)
        for r, g in zip(merged["txn_recall_pct_train"], merged["genuine_alert_rate_pct_train"])
    ]
    columns = ["rule", "status"]
    for metric in ["alerts_per_day", "cases_per_day", "precision_pct"]:
        columns += [f"{metric}_train", f"{metric}_test"]
    columns += ["expected_test_precision_pct"]
    for metric in ["genuine_alert_rate_pct", "txn_recall_pct", "value_detection_pct", "card_detection_pct"]:
        columns += [f"{metric}_train", f"{metric}_test"]
    result = merged[columns].copy()
    result["sort_key"] = result["rule"].isin(COMBINED)
    result = result.sort_values(["sort_key", "rule"]).drop(columns="sort_key")
    return result.round(3)


def main():
    result = compare()
    out_dir = OUTPUT_DIR / "pvt"
    out_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_dir / "pvt_rule_comparison.csv", index=False)
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
