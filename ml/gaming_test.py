"""Threshold-gaming test: synthetic fraud placed just under each rule threshold.

Usage: .venv\\Scripts\\python.exe ml/gaming_test.py   (after ml/train_ranker.py)
Writes outputs/ml/gaming_test.csv.

Each scenario runs on its own synthetic card with 60 days of normal history
(two transactions a day, $25 at 10:00 and $35 at 18:00, at five known
merchants), so its daily baseline is $60 and R7's 48-hour threshold is $600.
The table shows which layer, if any, catches each attempt:
  active rules (alert) -> the ML ranker only ever sees these
  shadow or retired rules (computed, no alert)
Scores from both ranker candidates (v1 and the monotonic candidate) are shown
for every row; for rows no active rule alerted on they are a what-if, because
the ranker only sees alerts in the live design. pct_higher_* is the share of
that model's real test alerts scored above the attempt.
"""

import pickle
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402

from features import all_row_features, build_rule_tables, load_txn_frame, model_matrix  # noqa: E402

from db import OUTPUT_DIR, connect  # noqa: E402

HISTORY_START = datetime(2020, 1, 1)
HISTORY_DAYS = 60
DAY_61 = HISTORY_START + timedelta(days=HISTORY_DAYS)


def history_rows():
    rows = []
    for day in range(HISTORY_DAYS):
        date = HISTORY_START + timedelta(days=day)
        merchant = f"known_merchant_{day % 5}"
        rows.append((date + timedelta(hours=10), 25.0, "misc_pos", merchant))
        rows.append((date + timedelta(hours=18), 35.0, "grocery_pos", merchant))
    return rows


def at(hour, minute=0):
    return DAY_61 + timedelta(hours=hour, minutes=minute)


SCENARIOS = [
    ("S1", "Just under R4: shopping_net $599.99 at 14:00",
     [(at(14), 599.99, "shopping_net", "known_merchant_0")]),
    ("S2", "Just under R3 and R4: shopping_net $599.99 at 23:30",
     [(at(23, 30), 599.99, "shopping_net", "known_merchant_0")]),
    ("S3", "Just under R4 (grocery_pos): $250.00 at 23:00",
     [(at(23), 250.00, "grocery_pos", "known_merchant_0")]),
    ("S4", "Just under R7: two shopping_net $252.50 at 12:00 and 13:00 (48h spend exactly $600.00)",
     [(at(12), 252.50, "shopping_net", "known_merchant_0"), (at(13), 252.50, "shopping_net", "known_merchant_0")]),
    ("S5", "Split purchase: three shopping_net $400 within 10 minutes at 23:30",
     [(at(23, 30), 400.0, "shopping_net", "known_merchant_0"), (at(23, 35), 400.0, "shopping_net", "known_merchant_0"),
      (at(23, 40), 400.0, "shopping_net", "known_merchant_0")]),
    ("S6", "Just at R6 (shadow): $750.00 at a new merchant, shopping_pos",
     [(at(14), 750.00, "shopping_pos", "new_merchant")]),
    ("S7", "Outside R4 categories: misc_pos $599.99 at 03:00",
     [(at(3), 599.99, "misc_pos", "known_merchant_0")]),
]

ACTIVE = ["flag_r3", "flag_r4", "flag_r7"]
SHADOW_OR_RETIRED = ["flag_r1", "flag_r2", "flag_r5", "flag_r6"]
RULE_NAMES = {"flag_r1": "R1", "flag_r2": "R2", "flag_r3": "R3", "flag_r4": "R4",
              "flag_r5": "R5", "flag_r6": "R6", "flag_r7": "R7"}


def run_scenario(scenario_id, attempt_rows):
    rows = [(ts, amt, cat, merchant, 0) for ts, amt, cat, merchant in history_rows()]
    rows += [(ts, amt, cat, merchant, 1) for ts, amt, cat, merchant in attempt_rows]
    frame = pd.DataFrame(rows, columns=["ts", "amt", "category", "merchant", "is_fraud"])
    frame["trans_num"] = [f"{scenario_id}-{i:04d}" for i in range(len(frame))]
    frame["card_id"] = "synthetic_card_0001"

    con = connect()
    load_txn_frame(con, frame)
    build_rule_tables(con)
    features = all_row_features(con)
    return features[features["is_fraud"] == 1]


def layer(row):
    active = [RULE_NAMES[c] for c in ACTIVE if row[c] == 1]
    other = [RULE_NAMES[c] for c in SHADOW_OR_RETIRED if row[c] == 1]
    if active:
        return "caught by active rule " + " ".join(active)
    if other:
        return "no alert; only shadow/retired " + " ".join(other) + " fired"
    return "no alert; nothing fired"


MODELS = ["v1", "monotonic"]


def main():
    saved = {}
    for name in MODELS:
        with open(OUTPUT_DIR / "ml" / f"model_{name}.pkl", "rb") as f:
            saved[name] = pickle.load(f)
    # Where a score would sit in a real queue: share of that model's test alerts scored higher.
    test_scores = pd.read_csv(OUTPUT_DIR / "ml" / "test_scores_by_model.csv")
    results = []
    for scenario_id, description, attempt_rows in SCENARIOS:
        attempts = run_scenario(scenario_id, attempt_rows)
        scores = {name: saved[name]["model"].predict_proba(model_matrix(attempts, saved[name]["categories"]))[:, 1]
                  for name in MODELS}
        for position, (_, row) in enumerate(attempts.iterrows()):
            results.append({
                "scenario": scenario_id,
                "description": description,
                "ts": row["ts"],
                "amt": row["amt"],
                "category": row["category"],
                "spend_48h_note": "R7 threshold here is $600 over 48 hours",
                "active_rules": " ".join(RULE_NAMES[c] for c in ACTIVE if row[c] == 1) or "-",
                "shadow_or_retired_rules": " ".join(RULE_NAMES[c] for c in SHADOW_OR_RETIRED if row[c] == 1) or "-",
                "layer": layer(row),
                "model_score_is_what_if": row["active_fired"] == 0,
            })
            for name in MODELS:
                score = float(scores[name][position])
                results[-1][f"score_{name}"] = round(score, 4)
                results[-1][f"pct_higher_{name}"] = round(100 * float((test_scores[f"score_{name}"] > score).mean()), 1)
    table = pd.DataFrame(results)
    table.to_csv(OUTPUT_DIR / "ml" / "gaming_test.csv", index=False)
    print(table.drop(columns=["description", "spend_48h_note", "ts", "category"]).to_string(index=False))


if __name__ == "__main__":
    main()
