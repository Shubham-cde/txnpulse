-- Per-rule performance on scored rows.
-- Expects table `flags` from sql/10_features_and_flags.sql (plus sql/15 for R8
-- in the test period). Rule columns are found by name (r<digit>_...), so a new
-- rule needs no change here beyond its catalogue row. A rule column that is
-- still a NULL placeholder is reported as implemented = false.

-- Status decides what counts as the live rule set:
--   active  - alerts, counts toward the alert budget and the combined metrics
--   shadow  - computed and measured, but does not alert (R8 until promoted)
--   retired - computed at its last version for monitoring only
CREATE OR REPLACE TABLE rule_catalogue(rule, version, status, action) AS
VALUES
    ('r1_velocity',                 '1.1', 'retired', 'ALERT'),
    ('r2_amount_spike',             '1.0', 'retired', 'STEP_UP'),
    ('r3_late_night_high_value',    '2.0', 'active',  'HOLD_CONFIRM'),
    ('r4_risky_category_amount',    '2.0', 'active',  'ALERT'),
    ('r5_distance_anomaly',         '1.0', 'retired', 'ALERT'),
    ('r6_new_merchant_high_amount', '2.0', 'active',  'STEP_UP'),
    ('r7_spend_burst',              '2.0', 'active',  'HOLD_CONFIRM'),
    ('r8_risk_list_hit',            '1.0', 'shadow',  'BLOCK / HOLD_CONFIRM by tier');

CREATE OR REPLACE TABLE scored_flags AS
SELECT * FROM flags WHERE is_scored;

-- INCLUDE NULLS keeps placeholder rules, so they show up as not implemented.
CREATE OR REPLACE TABLE rule_hits_long AS
SELECT h.*, c.status
FROM (
    SELECT *
    FROM (SELECT trans_num, card_id, ts, amt, is_fraud, COLUMNS('^r[0-9]+_') FROM scored_flags)
    UNPIVOT INCLUDE NULLS (hit FOR rule IN (COLUMNS('^r[0-9]+_')))
) h
JOIN rule_catalogue c USING (rule);

-- One row per scored transaction with how many active (and shadow) rules fired.
CREATE OR REPLACE TABLE txn_rules_fired AS
SELECT
    trans_num,
    ANY_VALUE(card_id)  AS card_id,
    ANY_VALUE(ts)       AS ts,
    ANY_VALUE(amt)      AS amt,
    ANY_VALUE(is_fraud) AS is_fraud,
    COUNT(*) FILTER (WHERE hit AND status = 'active')              AS active_fired,
    COUNT(*) FILTER (WHERE hit AND status IN ('active', 'shadow')) AS active_or_shadow_fired
FROM rule_hits_long
GROUP BY trans_num;

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
combined AS (
    -- A transaction counts once however many rules fired on it.
    SELECT
        'any_active' AS rule, TRUE AS implemented,
        COUNT(*) FILTER (WHERE active_fired > 0) AS alerts,
        COUNT(*) FILTER (WHERE active_fired > 0 AND is_fraud = 1) AS fraud_alerts
    FROM txn_rules_fired
    UNION ALL
    SELECT
        'any_active_or_shadow', TRUE,
        COUNT(*) FILTER (WHERE active_or_shadow_fired > 0),
        COUNT(*) FILTER (WHERE active_or_shadow_fired > 0 AND is_fraud = 1)
    FROM txn_rules_fired
)
SELECT
    r.rule,
    c.version,
    COALESCE(c.status, 'combined')                                  AS status,
    COALESCE(c.action, 'combined')                                  AS action,
    r.implemented,
    r.alerts,
    ROUND(r.alerts / p.days, 2)                                     AS alerts_per_day,
    r.fraud_alerts,
    ROUND(100.0 * r.fraud_alerts / NULLIF(r.alerts, 0), 2)          AS precision_pct,
    ROUND((r.alerts - r.fraud_alerts) / NULLIF(r.fraud_alerts, 0), 2) AS fp_per_fraud,
    ROUND(100.0 * r.fraud_alerts / p.total_fraud_txns, 2)           AS txn_recall_pct
FROM (SELECT * FROM per_rule UNION ALL SELECT * FROM combined) r
CROSS JOIN period p
LEFT JOIN rule_catalogue c USING (rule)
ORDER BY c.rule IS NULL, r.rule;

-- name: rule_overlap
-- How many active rules fire together on the same transaction.
SELECT
    active_fired                          AS active_rules_fired,
    COUNT(*)                              AS rows_alerted,
    COUNT(*) FILTER (WHERE is_fraud = 1)  AS fraud_rows
FROM txn_rules_fired
WHERE active_fired > 0
GROUP BY active_fired
ORDER BY active_fired;
