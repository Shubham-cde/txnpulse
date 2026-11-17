-- Test-period-only PVT views. src/run_rules.py runs this file only for
-- --period test. Expects txn (train history + test rows) and the tables from
-- sql/20 and sql/30.

-- Cards with no training history: none of their rows is unscored history.
CREATE OR REPLACE TABLE card_history_group AS
SELECT
    card_id,
    CASE WHEN BOOL_OR(NOT is_scored) THEN 'has_train_history' ELSE 'test_only' END AS card_group
FROM txn
GROUP BY card_id;

-- name: pvt_card_groups
-- Active rule set, split by whether the card had training history.
WITH fraud_cards AS (
    SELECT DISTINCT card_id FROM scored_flags WHERE is_fraud = 1
),
first_alert AS (
    SELECT card_id, MIN(ts) AS first_alert_ts
    FROM txn_rules_fired
    WHERE is_fraud = 1 AND active_fired > 0
    GROUP BY card_id
),
per_card AS (
    SELECT
        r.card_id,
        COUNT(*)                                                    AS fraud_txns,
        SUM(r.amt)                                                  AS fraud_amt,
        COUNT(*) FILTER (WHERE r.active_fired > 0)                  AS fraud_txns_alerted,
        COALESCE(SUM(r.amt) FILTER (WHERE r.active_fired > 0), 0)   AS fraud_amt_alerted,
        ANY_VALUE(a.first_alert_ts) IS NOT NULL                     AS detected,
        COUNT(*) FILTER (WHERE a.first_alert_ts IS NULL OR r.ts < a.first_alert_ts) AS fraud_txns_before,
        COALESCE(SUM(r.amt) FILTER (WHERE a.first_alert_ts IS NULL OR r.ts < a.first_alert_ts), 0)
                                                                    AS fraud_amt_before
    FROM txn_rules_fired r
    LEFT JOIN first_alert a USING (card_id)
    WHERE r.is_fraud = 1
    GROUP BY r.card_id
)
SELECT
    g.card_group,
    COUNT(*)                                                        AS compromised_cards,
    COUNT(*) FILTER (WHERE p.detected)                              AS cards_detected,
    ROUND(100.0 * COUNT(*) FILTER (WHERE p.detected) / COUNT(*), 2) AS card_detection_pct,
    SUM(p.fraud_txns)                                               AS fraud_txns,
    ROUND(100.0 * SUM(p.fraud_txns_alerted) / SUM(p.fraud_txns), 2) AS txn_recall_pct,
    ROUND(100.0 * SUM(p.fraud_amt_alerted) / SUM(p.fraud_amt), 2)   AS value_detection_pct,
    MEDIAN(p.fraud_txns_before)                                     AS median_fraud_txns_before,
    QUANTILE_CONT(p.fraud_txns_before, 0.9)                         AS p90_fraud_txns_before,
    ROUND(MEDIAN(p.fraud_amt_before), 2)                            AS median_fraud_amt_before,
    ROUND(QUANTILE_CONT(p.fraud_amt_before, 0.9), 2)                AS p90_fraud_amt_before
FROM per_card p
JOIN card_history_group g USING (card_id)
GROUP BY g.card_group
ORDER BY g.card_group;

-- name: pvt_test_only_cards
-- One row per card with no training history. Card numbers masked to the last 4 digits.
WITH test_only AS (
    SELECT card_id FROM card_history_group WHERE card_group = 'test_only'
),
card_rows AS (
    SELECT
        r.*,
        MIN(r.ts) FILTER (WHERE r.is_fraud = 1) OVER (PARTITION BY r.card_id) AS first_fraud_ts
    FROM txn_rules_fired r
    JOIN test_only USING (card_id)
),
first_alert AS (
    SELECT card_id, ARG_MIN(trans_num, (ts, trans_num)) AS trans_num, MIN(ts) AS first_alert_ts
    FROM card_rows
    WHERE is_fraud = 1 AND active_fired > 0
    GROUP BY card_id
),
first_alert_rules AS (
    SELECT h.trans_num, STRING_AGG(h.rule, ' ' ORDER BY h.rule) AS rules
    FROM rule_hits_long h
    JOIN first_alert USING (trans_num)
    WHERE h.hit AND h.status = 'active'
    GROUP BY h.trans_num
)
SELECT
    'XXXX' || RIGHT(c.card_id, 4)                                               AS card_masked,
    COUNT(*)                                                                    AS txns,
    COUNT(*) FILTER (WHERE c.is_fraud = 0 AND c.ts < c.first_fraud_ts)          AS genuine_txns_before_first_fraud,
    COUNT(*) FILTER (WHERE c.is_fraud = 1)                                      AS fraud_txns,
    ROUND(COALESCE(SUM(c.amt) FILTER (WHERE c.is_fraud = 1), 0), 2)             AS fraud_amt,
    COUNT(*) FILTER (WHERE c.is_fraud = 1 AND c.active_fired > 0)               AS fraud_txns_alerted,
    COUNT(*) FILTER (WHERE c.is_fraud = 1
        AND (a.first_alert_ts IS NULL OR c.ts < a.first_alert_ts))              AS fraud_txns_before_first_alert,
    ANY_VALUE(fr.rules)                                                         AS rules_on_first_alert
FROM card_rows c
LEFT JOIN first_alert a USING (card_id)
LEFT JOIN first_alert_rules fr ON fr.trans_num = a.trans_num
GROUP BY c.card_id
ORDER BY fraud_amt DESC;
