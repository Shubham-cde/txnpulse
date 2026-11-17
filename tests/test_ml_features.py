"""Leakage tests for the ML feature builder (ml/features.py, sql/60).

The builder must never use R8, labels or future transactions. Each test builds
a small synthetic card and runs the real rule and feature SQL on it.
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from db import connect, split_named_queries, SQL_DIR, run_sql_file
from features import (
    CATEGORY_FEATURE, FORBIDDEN_FEATURES, NUMERIC_FEATURES, all_row_features, build_rule_tables,
    load_txn_frame, model_matrix,
)
from uat import add_r8
import features as features_module

START = datetime(2020, 3, 1, 10, 0)
LISTED_MERCHANT = "fraud_Kozey-Boehm"  # very_high tier in risk list v1


def card_frame(extra_days=0):
    """40 days of normal spend, then late-night high-value spend (fires R3/R4/R7),
    then optional later days that must not change any earlier feature."""
    rows = []
    for day in range(40):
        rows.append((START + timedelta(days=day), 30.0, "misc_pos", f"merchant_{day % 4}", day % 7 == 0))
    rows.append((START + timedelta(days=40, hours=13, minutes=30), 700.0, "shopping_net", LISTED_MERCHANT, True))
    rows.append((START + timedelta(days=40, hours=13, minutes=40), 800.0, "shopping_net", "merchant_9", True))
    # Extra days are strictly after every row above, so they are the future for all of them.
    for day in range(extra_days):
        rows.append((START + timedelta(days=41 + day), 30.0, "misc_pos", f"merchant_{day % 4}", False))
        rows.append((START + timedelta(days=41 + day, hours=3), 1500.0, "shopping_net", "merchant_9", True))
    frame = pd.DataFrame(rows, columns=["ts", "amt", "category", "merchant", "is_fraud"])
    frame["is_fraud"] = frame["is_fraud"].astype(int)
    frame = frame.sort_values("ts").reset_index(drop=True)
    frame["trans_num"] = [f"t{ts:%Y%m%d%H%M}" for ts in frame["ts"]]
    frame["card_id"] = "card_test_0001"
    return frame


def features_for(frame, with_r8=False):
    con = connect()
    load_txn_frame(con, frame)
    if with_r8:
        # Mirror the test-period pipeline: sql/10, then R8 (sql/15), then sql/20.
        run_sql_file(con, SQL_DIR / "10_features_and_flags.sql")
        add_r8(con)
        preamble, _ = split_named_queries((SQL_DIR / "20_rule_performance.sql").read_text(encoding="utf-8"))
        con.execute(preamble)
    else:
        build_rule_tables(con)
    return con, all_row_features(con).set_index("trans_num")


def test_no_r8_even_when_r8_is_present_in_flags():
    con, features = features_for(card_frame(), with_r8=True)
    listed = con.execute("SELECT trans_num FROM flags WHERE r8_risk_list_hit").fetchall()
    assert listed, "the setup should put one transaction on the risk list"

    assert not [c for c in features.columns if "r8" in c or "risk_list" in c]
    flag_sum = features[[f"flag_r{i}" for i in range(1, 8)]].sum(axis=1)
    assert (features["rules_fired"] == flag_sum).all(), "rules_fired must count R1-R7 only"


def test_model_matrix_has_no_labels_ids_or_r8():
    _, features = features_for(card_frame())
    matrix = model_matrix(features.reset_index(), categories=["misc_pos", "shopping_net"])
    assert not FORBIDDEN_FEATURES.intersection(matrix.columns)
    assert not [c for c in matrix.columns if "fraud" in c or "r8" in c]


def test_model_matrix_rejects_a_forbidden_column(monkeypatch):
    _, features = features_for(card_frame())
    # If someone added the label to the feature list, the guard must stop it.
    monkeypatch.setattr(features_module, "NUMERIC_FEATURES", NUMERIC_FEATURES + ["is_fraud"])
    with pytest.raises(ValueError):
        features_module.model_matrix(features.reset_index(), categories=["misc_pos"])


def test_features_do_not_use_future_rows():
    base = card_frame()
    _, before = features_for(base)
    _, after = features_for(card_frame(extra_days=5))
    shared = before.index
    pd.testing.assert_frame_equal(
        before.loc[shared, NUMERIC_FEATURES + [CATEGORY_FEATURE]],
        after.loc[shared, NUMERIC_FEATURES + [CATEGORY_FEATURE]],
    )


def test_features_do_not_depend_on_labels():
    frame = card_frame()
    flipped = frame.assign(is_fraud=1 - frame["is_fraud"])
    _, original = features_for(frame)
    _, relabelled = features_for(flipped)
    pd.testing.assert_frame_equal(
        original[NUMERIC_FEATURES + [CATEGORY_FEATURE]],
        relabelled[NUMERIC_FEATURES + [CATEGORY_FEATURE]],
    )
    assert not np.array_equal(original["is_fraud"], relabelled["is_fraud"])


def test_category_columns_fixed_by_training_levels():
    _, features = features_for(card_frame())
    training_levels = ["grocery_pos", "shopping_net"]
    matrix = model_matrix(features.reset_index(), training_levels)
    assert [c for c in matrix.columns if c.startswith("category_")] == ["category_grocery_pos", "category_shopping_net"]
    # misc_pos was never seen in "training", so those rows get all-zero category columns.
    misc = features.reset_index()["category"] == "misc_pos"
    assert (matrix.loc[misc, ["category_grocery_pos", "category_shopping_net"]] == 0).all().all()
