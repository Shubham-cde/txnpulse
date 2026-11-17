-- Per-rule performance on scored rows.
-- Expects table `flags` from sql/10_features_and_flags.sql.
-- Rule columns are found by name (r<digit>_...), so a new rule needs no change here.
-- A rule column that is still a NULL placeholder is reported as implemented = false.

CREATE OR REPLACE TABLE rule_action(rule, action) AS
VALUES
    ('r1_velocity',                 'ALERT'),
    ('r2_amount_spike',             'STEP_UP'),
    ('r3_late_night_high_value',    'HOLD_CONFIRM'),
    ('r4_risky_category_amount',    'ALERT'),
    ('r5_distance_anomaly',         'ALERT'),
    ('r6_new_merchant_high_amount', 'STEP_UP'),
    ('r7_spend_burst_24h',          'HOLD_CONFIRM'),
    ('r8_risk_list_hit',            'BLOCK / HOLD by tier');

CREATE OR REPLACE TABLE scored_flags AS
SELECT * FROM flags WHERE is_scored;

-- INCLUDE NULLS keeps placeholder rules, so they show up as not implemented.
CREATE OR REPLACE TABLE rule_hits_long AS
SELECT *
FROM (SELECT trans_num, card_id, ts, amt, is_fraud, COLUMNS('^r[0-9]+_') FROM scored_flags)
UNPIVOT INCLUDE NULLS (hit FOR rule IN (COLUMNS('^r[0-9]+_')));

-- name: rule_performance
WITH period AS (
    SELECT
        COUNT(DISTINCT CAST(ts AS DATE)) AS days,
        SUM(is_fraud)                    AS total_fraud_txns
    FROM scored_flags
),
per_rule AS (
    SELECT
        rule,
        COUNT(hit) > 0                                  AS implemented,
        CASE WHEN COUNT(hit) > 0 THEN COUNT(*) FILTER (WHERE hit) END AS alerts,
        CASE WHEN COUNT(hit) > 0 THEN COUNT(*) FILTER (WHERE hit AND is_fraud = 1) END AS fraud_alerts
    FROM rule_hits_long
    GROUP BY rule
),
any_rule AS (
    -- A row counts once however many implemented rules fired on it.
    SELECT
        'any_rule'                                      AS rule,
        TRUE                                            AS implemented,
        COUNT(*)                                        AS alerts,
        COUNT(*) FILTER (WHERE is_fraud = 1)            AS fraud_alerts
    FROM (
        SELECT trans_num, ANY_VALUE(is_fraud) AS is_fraud
        FROM rule_hits_long
        WHERE hit
        GROUP BY trans_num
    )
)
SELECT
    r.rule,
    COALESCE(a.action, 'combined')                                  AS action,
    r.implemented,
    r.alerts,
    ROUND(r.alerts / p.days, 2)                                     AS alerts_per_day,
    r.fraud_alerts,
    ROUND(100.0 * r.fraud_alerts / NULLIF(r.alerts, 0), 2)          AS precision_pct,
    ROUND((r.alerts - r.fraud_alerts) / NULLIF(r.fraud_alerts, 0), 2) AS fp_per_fraud,
    ROUND(100.0 * r.fraud_alerts / p.total_fraud_txns, 2)           AS txn_recall_pct
FROM (SELECT * FROM per_rule UNION ALL SELECT * FROM any_rule) r
CROSS JOIN period p
LEFT JOIN rule_action a USING (rule)
ORDER BY r.rule = 'any_rule', r.rule;

-- name: rule_overlap
-- How many rules fire together on the same row; input for unique-catch analysis.
SELECT
    rules_fired,
    COUNT(*)                              AS rows_alerted,
    COUNT(*) FILTER (WHERE is_fraud = 1)  AS fraud_rows
FROM (
    SELECT trans_num, ANY_VALUE(is_fraud) AS is_fraud, COUNT(*) FILTER (WHERE hit) AS rules_fired
    FROM rule_hits_long
    GROUP BY trans_num
)
WHERE rules_fired > 0
GROUP BY rules_fired
ORDER BY rules_fired;
