"""Train and evaluate the ML alert ranker for rule set v2.1.

Usage: .venv\\Scripts\\python.exe ml/train_ranker.py
Writes outputs/ml/*.csv and outputs/ml/*.pkl.

Protocol (choices are made on train only):
  1. Validation split inside train: fit on alerts before 2020-04-01, validate on
     alerts from 2020-04-01 to the end of train.
  2. Warm-up check: each candidate is fitted on two windows, all of train and
     2019-07-01 onwards, because history features are unreliable while cards
     have little history.
  3. Model v1 = best validation PR-AUC among logistic regression and unconstrained
     gradient boosting. v1 was the first model to score the test period.
  4. Monotonic candidate = best validation PR-AUC among gradient boosting with the
     score constrained to be non-decreasing in amt, amt_to_avg30 and spend_24h.
     It was added after v1 had scored test, so its test figures are an impact
     estimate, not out-of-sample validation.
  5. The documented model is whichever of v1 and the candidate has the higher
     validation PR-AUC.
"""

import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import average_precision_score  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from alert_note import build_alert_note_prompt  # noqa: E402
from explain import mean_abs_importance, shap_values, top_reason_codes  # noqa: E402
from features import category_levels, load_period_features, model_matrix  # noqa: E402
from ranking import alert_units, case_units, queue_metrics, ranking_scores  # noqa: E402

from db import OUTPUT_DIR  # noqa: E402

OUT_DIR = OUTPUT_DIR / "ml"
VALIDATION_START = pd.Timestamp("2020-04-01")
WINDOWS = {"all_train": pd.Timestamp("2019-01-01"), "from_2019_07": pd.Timestamp("2019-07-01")}
# Train alerts per day: median 33, 25th percentile 22. Queues at or below a typical
# day are where the order matters; a queue larger than the day reviews everything.
QUEUE_SIZES = [10, 20, 30]
# More money, a bigger jump against the card's average, or more 24-hour spend should
# never lower the score. Without this, the model can rank fraud above the simulator's
# usual amounts low (the $1,320 worked example).
MONOTONIC_INCREASING = ["amt", "amt_to_avg30", "spend_24h"]


def candidate_configs():
    configs = [{"family": "logistic_regression", "C": 1.0}]
    for monotonic in (False, True):
        for learning_rate in (0.05, 0.1):
            for max_leaf_nodes in (15, 31):
                for max_iter in (200, 400):
                    configs.append({
                        "family": "hist_gradient_boosting_monotonic" if monotonic else "hist_gradient_boosting",
                        "learning_rate": learning_rate, "max_leaf_nodes": max_leaf_nodes, "max_iter": max_iter,
                    })
    return configs


def monotonic_constraints(columns):
    return [1 if column in MONOTONIC_INCREASING else 0 for column in columns]


def build_model(config, columns):
    if config["family"] == "logistic_regression":
        return make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            StandardScaler(),
            LogisticRegression(C=config["C"], class_weight="balanced", max_iter=2000),
        )
    constraints = monotonic_constraints(columns) if config["family"].endswith("_monotonic") else None
    return HistGradientBoostingClassifier(
        learning_rate=config["learning_rate"], max_leaf_nodes=config["max_leaf_nodes"],
        max_iter=config["max_iter"], class_weight="balanced", early_stopping=False, random_state=0,
        monotonic_cst=constraints,
    )


def fit_and_score(config, fit_rows, score_rows, categories):
    fit_matrix = model_matrix(fit_rows, categories)
    model = build_model(config, list(fit_matrix.columns))
    model.fit(fit_matrix, fit_rows["is_fraud"])
    return model, model.predict_proba(model_matrix(score_rows, categories))[:, 1]


def validation_search(train_alerts, categories, validation_fraud_amt):
    validation = train_alerts[train_alerts["ts"] >= VALIDATION_START]
    rows = []
    for window, start in WINDOWS.items():
        fit_rows = train_alerts[(train_alerts["ts"] >= start) & (train_alerts["ts"] < VALIDATION_START)]
        for config in candidate_configs():
            _, scores = fit_and_score(config, fit_rows, validation, categories)
            metrics = queue_metrics(alert_units(validation), pd.DataFrame({"model_score": scores},
                                    index=validation.index), QUEUE_SIZES, validation_fraud_amt)
            row = {"window": window, "fit_alerts": len(fit_rows), "fit_fraud": int(fit_rows["is_fraud"].sum()),
                   **config, "val_pr_auc": round(average_precision_score(validation["is_fraud"], scores), 4)}
            for _, m in metrics.iterrows():
                row[f"val_precision_at_{m['k']}"] = m["precision_at_k_pct"]
                row[f"val_value_queue_at_{m['k']}"] = m["value_at_k_queue_pct"]
            rows.append(row)
    return pd.DataFrame(rows).sort_values("val_pr_auc", ascending=False).reset_index(drop=True)


def config_of(row):
    config = {"family": row["family"]}
    if row["family"] == "logistic_regression":
        config["C"] = float(row["C"])
    else:
        config.update(learning_rate=float(row["learning_rate"]), max_leaf_nodes=int(row["max_leaf_nodes"]),
                      max_iter=int(row["max_iter"]))
    return config


def compare_rankings(alerts, model_scores, all_fraud_amt):
    scores = ranking_scores(alerts, model_scores)
    alert_level = queue_metrics(alert_units(alerts), scores, QUEUE_SIZES, all_fraud_amt).assign(level="alert")
    units, opening_scores = case_units(alerts, scores)
    case_level = queue_metrics(units, opening_scores, QUEUE_SIZES, all_fraud_amt).assign(level="case")
    return pd.concat([alert_level, case_level], ignore_index=True)


def worked_examples(alerts):
    """Five deterministic examples, picked with model v1's scores so both models can be
    compared on the same alerts."""
    ordered = alerts.sort_values(["score_v1", "trans_num"], ascending=[False, True])
    fraud, genuine = ordered[ordered["is_fraud"] == 1], ordered[ordered["is_fraud"] == 0]
    alert_only_fraud = fraud[fraud["strongest_action_severity"] == 1]
    hold_genuine = genuine[genuine["strongest_action_severity"] == 3]
    return [
        ("highest-scored fraud", fraud.index[0]),
        ("highest-scored genuine alert (false positive at the top)", genuine.index[0]),
        ("fraud raised only by R4 (ALERT) but ranked high by the model", alert_only_fraud.index[0]),
        ("genuine HOLD_CONFIRM alert pushed down by the model", hold_genuine.index[-1]),
        ("lowest-scored fraud (the model would review it last)", fraud.index[-1]),
    ]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    train_alerts, train_daily_fraud = load_period_features("train")
    test_alerts, test_daily_fraud = load_period_features("test")
    categories = category_levels(train_alerts)
    validation_fraud_amt = train_daily_fraud[train_daily_fraud.index >= VALIDATION_START.date()].sum()
    test_fraud_amt = test_daily_fraud.sum()

    search = validation_search(train_alerts, categories, validation_fraud_amt)
    search.to_csv(OUT_DIR / "validation_search.csv", index=False)
    v1_row = search[search["family"] != "hist_gradient_boosting_monotonic"].iloc[0]
    mono_row = search[search["family"] == "hist_gradient_boosting_monotonic"].iloc[0]
    candidates = {
        "v1": {"row": v1_row, "test_label": "out-of-sample validation (first and only test scoring of v1)"},
        "monotonic": {"row": mono_row, "test_label": "impact estimate, not out-of-sample validation"},
    }
    documented = "v1" if v1_row["val_pr_auc"] >= mono_row["val_pr_auc"] else "monotonic"

    validation = train_alerts[train_alerts["ts"] >= VALIDATION_START]
    scored = test_alerts.copy()
    models = {}
    for name, candidate in candidates.items():
        config, window = config_of(candidate["row"]), candidate["row"]["window"]
        candidate.update(config=config, window=window)
        fit_rows = train_alerts[(train_alerts["ts"] >= WINDOWS[window]) & (train_alerts["ts"] < VALIDATION_START)]
        _, val_scores = fit_and_score(config, fit_rows, validation, categories)
        compare_rankings(validation, val_scores, validation_fraud_amt).to_csv(
            OUT_DIR / f"validation_rankings_{name}.csv", index=False)
        final_fit = train_alerts[train_alerts["ts"] >= WINDOWS[window]]
        model, test_scores = fit_and_score(config, final_fit, test_alerts, categories)
        compare_rankings(test_alerts, test_scores, test_fraud_amt).assign(test_label=candidate["test_label"]).to_csv(
            OUT_DIR / f"test_rankings_{name}.csv", index=False)
        models[name] = model
        scored[f"score_{name}"] = test_scores
        scored[f"daily_rank_{name}"] = scored.groupby(scored["ts"].dt.date)[f"score_{name}"].rank(
            ascending=False, method="first")
        with open(OUT_DIR / f"model_{name}.pkl", "wb") as f:
            pickle.dump({"model": model, "categories": categories, "config": config, "window": window}, f)
        candidate["final_fit_alerts"] = len(final_fit)
        print(f"{name}: {window} {config} val PR-AUC {candidate['row']['val_pr_auc']}")

    decision = {
        "documented_model": documented,
        "rule": "higher validation PR-AUC (validation split inside train); test not used",
        "validation_start": str(VALIDATION_START.date()),
        "queue_sizes": QUEUE_SIZES,
        "test_alerts": len(test_alerts), "test_fraud": int(test_alerts["is_fraud"].sum()),
        "test_fraud_amt_all": round(float(test_fraud_amt), 2),
        "candidates": {name: {"window": c["window"], "config": c["config"], "val_pr_auc": float(c["row"]["val_pr_auc"]),
                              "final_fit_alerts": c["final_fit_alerts"], "test_figures": c["test_label"]}
                       for name, c in candidates.items()},
    }
    (OUT_DIR / "model_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    print(f"documented model: {documented}")

    # The documented model is the one saved as model.pkl and explained with SHAP.
    with open(OUT_DIR / "model.pkl", "wb") as f:
        pickle.dump({"model": models[documented], "categories": categories, "name": documented,
                     "config": candidates[documented]["config"], "window": candidates[documented]["window"]}, f)
    test_matrix = model_matrix(test_alerts, categories)
    reasons = {}
    for name, model in models.items():
        contributions = shap_values(model, test_matrix)
        if name == documented:
            mean_abs_importance(contributions).rename("mean_abs_shap").to_csv(OUT_DIR / "shap_importance.csv")
        reasons[name] = top_reason_codes(contributions, test_alerts)

    documented_scores = scored.assign(model_score=scored[f"score_{documented}"])
    output = documented_scores.assign(
        card=lambda d: "XXXX" + d["card_id"].str[-4:],
        daily_rank=documented_scores[f"daily_rank_{documented}"],
        reason_codes=reasons[documented].map(lambda r: " ".join(code for code, _ in r)),
    )[["trans_num", "ts", "card", "category", "amt", "active_rules", "strongest_action_severity",
       "model_score", "daily_rank", "is_fraud", "reason_codes"]]
    output.to_csv(OUT_DIR / "test_alert_scores.csv", index=False)
    scored[["trans_num", "is_fraud"] + [f"score_{name}" for name in models]].to_csv(
        OUT_DIR / "test_scores_by_model.csv", index=False)

    examples = []
    for label, idx in worked_examples(scored):
        row = scored.loc[idx]
        example = {
            "example": label, "ts": row["ts"], "card": "XXXX" + row["card_id"][-4:], "category": row["category"],
            "amt": round(row["amt"], 2), "active_rules": row["active_rules"],
            "alerts_that_day": int((scored["ts"].dt.date == row["ts"].date()).sum()),
            "is_fraud": int(row["is_fraud"]),
        }
        for name in models:
            example[f"score_{name}"] = round(row[f"score_{name}"], 4)
            example[f"daily_rank_{name}"] = int(row[f"daily_rank_{name}"])
            example[f"reasons_{name}"] = "; ".join(f"{code} ({value:+.2f})" for code, value in reasons[name][idx])
        note_input = row.copy()
        note_input["model_score"] = row[f"score_{documented}"]
        example["alert_note_prompt"] = build_alert_note_prompt(note_input, [c for c, _ in reasons[documented][idx]])
        examples.append(example)
    pd.DataFrame(examples).to_csv(OUT_DIR / "worked_examples.csv", index=False)

    for name in models:
        table = pd.read_csv(OUT_DIR / f"test_rankings_{name}.csv")
        print(f"\n{name} ({candidates[name]['test_label']}):")
        print(table[table["method"] == "model_score"].to_string(index=False))


if __name__ == "__main__":
    main()
