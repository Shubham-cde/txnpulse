-- Features for ML alert prioritisation: one row per scored transaction.
-- Expects tables flags (sql/10), scored_flags, rule_catalogue, rule_hits_long and
-- txn_rules_fired (sql/20). Read by ml/features.py, which keeps only alerted rows.
--
-- Every feature comes from sql/10, where windows end at the current row and
-- baselines exclude it, so nothing here can see the future.
-- Deliberately excluded:
--   * is_fraud as a feature (it is returned only as the label column)
--   * any past-label feature (fraud history of the card or merchant): labels
--     arrive late in production, so the model could not have them at scoring time
--   * R8: its risk list was built from train labels, so r8 on train rows would leak
--   * card, location and other personal fields (card_id is kept as an ID for
--     case grouping only)

WITH action_rank(action, severity) AS (
    VALUES ('ALERT', 1), ('STEP_UP', 2), ('HOLD_CONFIRM', 3), ('BLOCK', 4)
),
active_hits AS (
    SELECT
        h.trans_num,
        MAX(ar.severity)                                                        AS strongest_action_severity,
        STRING_AGG(UPPER(SPLIT_PART(h.rule, '_', 1)), ' ' ORDER BY h.rule)      AS active_rules
    FROM rule_hits_long h
    JOIN rule_catalogue c USING (rule)
    JOIN action_rank ar ON ar.action = c.action
    WHERE h.hit AND h.status = 'active'
    GROUP BY h.trans_num
)
SELECT
    -- IDs and label (not features)
    f.trans_num,
    f.card_id,
    f.ts,
    f.is_fraud,
    t.active_fired,
    COALESCE(a.strongest_action_severity, 0)           AS strongest_action_severity,
    a.active_rules,

    -- Features
    f.amt,
    f.amt / NULLIF(f.avg_amt_prev30, 0)                AS amt_to_avg30,
    f.txn_count_60m,
    f.spend_24h,
    f.hour_of_day,
    f.category,
    f.distance_km,
    CAST(f.first_visit AS INTEGER)                     AS first_visit,
    CAST(f.r1_velocity AS INTEGER)
        + CAST(f.r2_amount_spike AS INTEGER)
        + CAST(f.r3_late_night_high_value AS INTEGER)
        + CAST(f.r4_risky_category_amount AS INTEGER)
        + CAST(f.r5_distance_anomaly AS INTEGER)
        + CAST(f.r6_new_merchant_high_amount AS INTEGER)
        + CAST(f.r7_spend_burst AS INTEGER)            AS rules_fired,
    CAST(f.r1_velocity AS INTEGER)                     AS flag_r1,
    CAST(f.r2_amount_spike AS INTEGER)                 AS flag_r2,
    CAST(f.r3_late_night_high_value AS INTEGER)        AS flag_r3,
    CAST(f.r4_risky_category_amount AS INTEGER)        AS flag_r4,
    CAST(f.r5_distance_anomaly AS INTEGER)             AS flag_r5,
    CAST(f.r6_new_merchant_high_amount AS INTEGER)     AS flag_r6,
    CAST(f.r7_spend_burst AS INTEGER)                  AS flag_r7
FROM scored_flags f
JOIN txn_rules_fired t USING (trans_num)
LEFT JOIN active_hits a USING (trans_num)
ORDER BY f.ts, f.trans_num
