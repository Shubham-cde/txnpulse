-- Value, card, loss and unique-catch metrics.
-- Expects tables from sql/20_rule_performance.sql: scored_flags, rule_hits_long.
-- Both already hold only scored rows (is_scored), so nothing here can count
-- training history loaded for the test period.
-- review_cost comes from src/run_rules.py --review-cost (default 5).
-- A rule column that is still a NULL placeholder gets NULL metrics, as in sql/20.

-- One row per scored transaction with how many rules fired on it.
-- rules_fired > 0 is the any_rule alert; rules_fired = 1 marks a unique catch.
CREATE OR REPLACE TABLE txn_rules_fired AS
SELECT
    trans_num,
    ANY_VALUE(card_id)          AS card_id,
    ANY_VALUE(ts)               AS ts,
    ANY_VALUE(amt)              AS amt,
    ANY_VALUE(is_fraud)         AS is_fraud,
    COUNT(*) FILTER (WHERE hit) AS rules_fired
FROM rule_hits_long
GROUP BY trans_num;

-- name: value_detection
WITH totals AS (
    SELECT SUM(amt) FILTER (WHERE is_fraud = 1) AS total_fraud_amt
    FROM scored_flags
),
per_rule AS (
    SELECT
        rule,
        CASE WHEN COUNT(hit) > 0 THEN COUNT(*) FILTER (WHERE hit) END AS alerts,
        CASE WHEN COUNT(hit) > 0
             THEN COALESCE(SUM(amt) FILTER (WHERE hit AND is_fraud = 1), 0) END AS fraud_amt_caught
    FROM rule_hits_long
    GROUP BY rule
),
any_rule AS (
    SELECT
        'any_rule'                                              AS rule,
        COUNT(*) FILTER (WHERE rules_fired > 0)                 AS alerts,
        COALESCE(SUM(amt) FILTER (WHERE rules_fired > 0 AND is_fraud = 1), 0) AS fraud_amt_caught
    FROM txn_rules_fired
)
SELECT
    r.rule,
    r.alerts,
    ROUND(r.fraud_amt_caught, 2)                                    AS fraud_amt_caught,
    ROUND(t.total_fraud_amt, 2)                                     AS total_fraud_amt,
    ROUND(100.0 * r.fraud_amt_caught / t.total_fraud_amt, 2)        AS value_detection_pct,
    getvariable('review_cost')                                      AS review_cost,
    ROUND(r.fraud_amt_caught - r.alerts * getvariable('review_cost'), 2) AS net_benefit
FROM (SELECT * FROM per_rule UNION ALL SELECT * FROM any_rule) r
CROSS JOIN totals t
ORDER BY r.rule = 'any_rule', r.rule;

-- name: card_detection
-- A card counts as detected only if an alert landed on one of its fraud rows;
-- an alert on its genuine spending does not count.
WITH totals AS (
    SELECT COUNT(DISTINCT card_id) FILTER (WHERE is_fraud = 1) AS compromised_cards
    FROM scored_flags
),
per_rule AS (
    SELECT
        rule,
        CASE WHEN COUNT(hit) > 0
             THEN COUNT(DISTINCT card_id) FILTER (WHERE hit AND is_fraud = 1) END AS cards_detected
    FROM rule_hits_long
    GROUP BY rule
),
any_rule AS (
    SELECT
        'any_rule' AS rule,
        COUNT(DISTINCT card_id) FILTER (WHERE rules_fired > 0 AND is_fraud = 1) AS cards_detected
    FROM txn_rules_fired
)
SELECT
    r.rule,
    t.compromised_cards,
    r.cards_detected,
    ROUND(100.0 * r.cards_detected / t.compromised_cards, 2) AS card_detection_pct
FROM (SELECT * FROM per_rule UNION ALL SELECT * FROM any_rule) r
CROSS JOIN totals t
ORDER BY r.rule = 'any_rule', r.rule;

-- name: loss_before_first_alert
-- Any rule. For each compromised card: fraud rows and fraud amount strictly
-- before the first fraud row that any rule alerted on. "Strictly before" means
-- a fraud row at the same second as that first alert counts as caught, not lost.
-- A card never alerted on a fraud row loses all of its scored fraud.
WITH first_alert AS (
    SELECT card_id, MIN(ts) AS first_alert_ts
    FROM txn_rules_fired
    WHERE is_fraud = 1 AND rules_fired > 0
    GROUP BY card_id
),
per_card AS (
    SELECT
        f.card_id,
        a.first_alert_ts IS NULL AS never_alerted,
        COUNT(*) FILTER (WHERE a.first_alert_ts IS NULL OR f.ts < a.first_alert_ts) AS fraud_txns_before,
        COALESCE(SUM(f.amt) FILTER (WHERE a.first_alert_ts IS NULL OR f.ts < a.first_alert_ts), 0)
            AS fraud_amt_before
    FROM txn_rules_fired f
    LEFT JOIN first_alert a USING (card_id)
    WHERE f.is_fraud = 1
    GROUP BY f.card_id, a.first_alert_ts
)
SELECT
    'any_rule'                                           AS rule,
    COUNT(*)                                             AS compromised_cards,
    COUNT(*) FILTER (WHERE never_alerted)                AS never_alerted_cards,
    MEDIAN(fraud_txns_before)                            AS median_fraud_txns_before,
    QUANTILE_CONT(fraud_txns_before, 0.9)                AS p90_fraud_txns_before,
    ROUND(MEDIAN(fraud_amt_before), 2)                   AS median_fraud_amt_before,
    ROUND(QUANTILE_CONT(fraud_amt_before, 0.9), 2)       AS p90_fraud_amt_before
FROM per_card;

-- name: unique_catches
-- Fraud rows this rule caught and no other implemented rule did.
-- Placeholder rules have NULL hits, so they never count as "another rule".
SELECT
    h.rule,
    CASE WHEN COUNT(h.hit) > 0
         THEN COUNT(*) FILTER (WHERE h.hit AND h.is_fraud = 1) END              AS fraud_alerts,
    CASE WHEN COUNT(h.hit) > 0
         THEN COUNT(*) FILTER (WHERE h.hit AND h.is_fraud = 1 AND r.rules_fired = 1) END
                                                                                AS unique_fraud_catches,
    CASE WHEN COUNT(h.hit) > 0
         THEN ROUND(COALESCE(SUM(h.amt) FILTER (WHERE h.hit AND h.is_fraud = 1 AND r.rules_fired = 1), 0), 2) END
                                                                                AS unique_fraud_amt
FROM rule_hits_long h
JOIN txn_rules_fired r USING (trans_num)
GROUP BY h.rule
ORDER BY h.rule;
