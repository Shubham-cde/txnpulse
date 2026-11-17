"""Daily alert queues: ranking methods, precision@K, value@K, PR-AUC and case grouping.

Every method ranks the same alerts within each calendar day. Ties in the two
coarse methods (rules fired, strongest action) are broken by amount, the way an
analyst would sort a queue.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

# Amounts are below 1e6, so these composite scores sort by the first key, then amount.
TIE_BREAK_SCALE = 1e6

RANKING_METHODS = ["model_score", "rules_fired", "strongest_action", "amount"]


def ranking_scores(alerts, model_scores):
    """One sortable score per alert for each ranking method (higher = reviewed first)."""
    return pd.DataFrame({
        "model_score": model_scores,
        "rules_fired": alerts["active_fired"] * TIE_BREAK_SCALE + alerts["amt"],
        "strongest_action": alerts["strongest_action_severity"] * TIE_BREAK_SCALE + alerts["amt"],
        "amount": alerts["amt"],
    }, index=alerts.index)


def queue_metrics(units, scores, queue_sizes, all_fraud_amt=None):
    """Precision@K and value@K for daily queues.

    units: one row per queue item with columns day, is_fraud, fraud_amt.
    precision@K          = fraud items in the daily top K / items reviewed (pooled over
                           days; a day with fewer than K items contributes all of them)
    value@K (queue)      = fraud amount in the daily top K / fraud amount in the alert queue
                           (all alerted items of the period)
    value@K (all fraud)  = fraud amount in the daily top K / ALL fraud amount of the period,
                           alerted or not (only when all_fraud_amt is given)
    """
    rows = []
    queue_fraud_amt = units["fraud_amt"].sum()
    for method in scores.columns:
        ranked = units.assign(score=scores[method].values)
        ranked = ranked.sort_values(["day", "score"], ascending=[True, False], kind="mergesort")
        ranked["position"] = ranked.groupby("day").cumcount() + 1
        for k in queue_sizes:
            top = ranked[ranked["position"] <= k]
            rows.append({
                "method": method,
                "k": k,
                "reviewed": len(top),
                "fraud_in_queue": int(top["is_fraud"].sum()),
                "precision_at_k_pct": round(100 * top["is_fraud"].mean(), 2),
                "value_at_k_queue_pct": round(100 * top["fraud_amt"].sum() / queue_fraud_amt, 2),
            })
            if all_fraud_amt is not None:
                rows[-1]["value_at_k_all_fraud_pct"] = round(100 * top["fraud_amt"].sum() / all_fraud_amt, 2)
    result = pd.DataFrame(rows)
    pr_auc = {m: round(average_precision_score(units["is_fraud"], scores[m]), 4) for m in scores.columns}
    result["pr_auc"] = result["method"].map(pr_auc)
    return result


def alert_units(alerts):
    return pd.DataFrame({
        "day": alerts["ts"].dt.date.values,
        "is_fraud": alerts["is_fraud"].values,
        "fraud_amt": np.where(alerts["is_fraud"] == 1, alerts["amt"], 0.0),
    }, index=alerts.index)


def assign_cases(alerts):
    """Case id per alert: a case opens with an alert and absorbs later alerts on the
    same card within 24 hours of the opening alert (same definition as sql/30)."""
    ordered = alerts.sort_values(["card_id", "ts", "trans_num"])
    case_ids = pd.Series(index=ordered.index, dtype="int64")
    case_id, current_card, case_start = -1, None, None
    for idx, card, ts in zip(ordered.index, ordered["card_id"], ordered["ts"]):
        if card != current_card or ts > case_start + pd.Timedelta(hours=24):
            case_id += 1
            current_card, case_start = card, ts
        case_ids[idx] = case_id
    return case_ids.reindex(alerts.index)


def case_units(alerts, scores):
    """One queue item per case, ranked by its OPENING alert's scores (known when the case
    opens, so no later alert leaks into the ranking). A case is fraud if any of its
    alerts is fraud; its value is the fraud amount across all its alerts."""
    with_cases = alerts.assign(
        case_id=assign_cases(alerts),
        fraud_amt=np.where(alerts["is_fraud"] == 1, alerts["amt"], 0.0),
    )
    opening = with_cases.sort_values(["ts", "trans_num"]).groupby("case_id").head(1).sort_values("case_id")
    per_case = with_cases.groupby("case_id").agg(is_fraud=("is_fraud", "max"), fraud_amt=("fraud_amt", "sum"))
    units = pd.DataFrame({
        "day": opening["ts"].dt.date.values,
        "is_fraud": per_case.loc[opening["case_id"], "is_fraud"].values,
        "fraud_amt": per_case.loc[opening["case_id"], "fraud_amt"].values,
    })
    opening_scores = scores.loc[opening.index].reset_index(drop=True)
    return units, opening_scores
