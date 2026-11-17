"""SHAP contributions turned into short reason codes for analysts.

Only risk-increasing contributions (positive SHAP) become reason codes: the
analyst needs to know why an alert was ranked high. The one-hot category
columns are summed into one "category" contribution before ranking.
"""

import numpy as np
import pandas as pd
import shap

RULE_CODES = {
    "flag_r1": "VELOCITY_RULE",
    "flag_r2": "AMT_SPIKE_RULE",
    "flag_r3": "LATE_NIGHT_HIGH_VALUE",
    "flag_r4": "RISKY_CATEGORY_AMT",
    "flag_r5": "DISTANCE_RULE",
    "flag_r6": "NEW_MERCHANT_HIGH_AMT",
    "flag_r7": "SPEND_BURST_48H",
}


def shap_values(model, matrix):
    """SHAP values on the log-odds scale for a fitted tree model or linear pipeline."""
    if hasattr(model, "named_steps"):
        # Linear baseline: explain the logistic step on the transformed inputs.
        transformed = model[:-1].transform(matrix)
        explainer = shap.LinearExplainer(model[-1], transformed)
        values = explainer.shap_values(transformed)[:, : matrix.shape[1]]
    else:
        values = shap.TreeExplainer(model).shap_values(matrix)
    return pd.DataFrame(np.asarray(values), columns=matrix.columns, index=matrix.index)


def group_categories(contributions):
    category_columns = [c for c in contributions.columns if c.startswith("category_")]
    grouped = contributions.drop(columns=category_columns)
    grouped["category"] = contributions[category_columns].sum(axis=1)
    return grouped


def reason_code(feature, row):
    """Short code for one feature, using the alert's own value so the code reads true."""
    value = row.get(feature)
    if feature == "amt":
        return f"HIGH_AMT_{int(row['amt'])}"
    if feature == "amt_to_avg30":
        if pd.isna(value):
            return "NO_CARD_HISTORY"
        return f"AMT_{int(round(value))}X_AVG" if value >= 2 else "AMT_NEAR_AVG"
    if feature == "txn_count_60m":
        return f"VELOCITY_{int(value)}_IN_60M"
    if feature == "spend_24h":
        return f"SPEND_24H_{int(value)}"
    if feature == "hour_of_day":
        return "LATE_NIGHT" if value >= 22 or value < 4 else f"HOUR_{int(value):02d}"
    if feature == "distance_km":
        return f"DISTANCE_{int(value)}KM"
    if feature == "first_visit":
        return "NEW_MERCHANT" if value == 1 else "REPEAT_MERCHANT"
    if feature == "rules_fired":
        return f"RULES_FIRED_{int(value)}"
    if feature in RULE_CODES:
        return RULE_CODES[feature] if value == 1 else f"NO_{RULE_CODES[feature]}"
    if feature == "category":
        return f"CAT_{str(row['category']).upper()}"
    return feature.upper()


def top_reason_codes(contributions, alerts, n=3):
    """Up to n reason codes per alert, from the largest positive grouped contributions."""
    grouped = group_categories(contributions)
    codes = []
    for idx in grouped.index:
        row_contrib = grouped.loc[idx]
        positive = row_contrib[row_contrib > 0].sort_values(ascending=False).head(n)
        row = alerts.loc[idx]
        codes.append([(reason_code(f, row), round(float(v), 3)) for f, v in positive.items()])
    return pd.Series(codes, index=grouped.index)


def mean_abs_importance(contributions):
    return group_categories(contributions).abs().mean().sort_values(ascending=False)
