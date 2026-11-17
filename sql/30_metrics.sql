-- Value, card, loss, unique-catch, case, first-alert, action and monthly metrics.
-- Expects tables from sql/20_rule_performance.sql: scored_flags, rule_catalogue,
-- rule_hits_long, txn_rules_fired. All hold scored rows only (is_scored), so
-- training history loaded for the test period is never counted.
-- review_cost comes from src/run_rules.py --review-cost (default 5).
-- "any_active" is the live rule set; "any_active_or_shadow" adds shadow rules.

-- Every alerted row, per rule and per combined set.
CREATE OR REPLACE TABLE alerts_long AS
SELECT rule, trans_num, card_id, ts, amt, is_fraud FROM rule_hits_long WHERE hit
UNION ALL
SELECT 'any_active', trans_num, card_id, ts, amt, is_fraud FROM txn_rules_fired WHERE active_fired > 0
UNION ALL
SELECT 'any_active_or_shadow', trans_num, card_id, ts, amt, is_fraud FROM txn_rules_fired WHERE active_or_shadow_fired > 0;

-- Every rule plus the combined sets. A placeholder rule (all NULL) is not implemented.
CREATE OR REPLACE TABLE metric_rules AS
SELECT rule, COUNT(hit) > 0 AS implemented FROM rule_hits_long GROUP BY rule
UNION ALL
SELECT * FROM (VALUES ('any_active', TRUE), ('any_active_or_shadow', TRUE)) v(rule, implemented);

CREATE OR REPLACE TABLE period_totals AS
SELECT
    COUNT(DISTINCT CAST(ts AS DATE))                         AS days,
    SUM(amt) FILTER (WHERE is_fraud = 1)                     AS total_fraud_amt,
    COUNT(DISTINCT card_id) FILTER (WHERE is_fraud = 1)      AS compromised_cards
FROM scored_flags;

-- Case grouping: an alert opens a case for its card; further alerts on that card
-- within 24 hours of the opening alert join the same case. Built for the active
-- and shadow rules and the combined sets only (retired rules raise no cases).
CREATE OR REPLACE TABLE case_input AS
SELECT
    a.rule, a.card_id, a.ts,
    ROW_NUMBER() OVER (PARTITION BY a.rule, a.card_id ORDER BY a.ts, a.trans_num) AS rn
FROM alerts_long a
LEFT JOIN rule_catalogue c USING (rule)
WHERE c.status IS NULL OR c.status IN ('active', 'shadow');

CREATE OR REPLACE TABLE alert_cases AS
WITH RECURSIVE assigned(rule, card_id, rn, ts, case_start) AS (
    SELECT rule, card_id, rn, ts, ts FROM case_input WHERE rn = 1
    UNION ALL
    SELECT
        i.rule, i.card_id, i.rn, i.ts,
        CASE WHEN i.ts <= a.case_start + INTERVAL 24 HOURS THEN a.case_start ELSE i.ts END
    FROM assigned a
    JOIN case_input i ON i.rule = a.rule AND i.card_id = a.card_id AND i.rn = a.rn + 1
)
SELECT * FROM assigned;

-- name: value_detection
WITH per_rule AS (
    SELECT
        rule,
        COUNT(*)                                            AS alerts,
        COALESCE(SUM(amt) FILTER (WHERE is_fraud = 1), 0)   AS fraud_amt_caught
    FROM alerts_long
    GROUP BY rule
)
SELECT
    m.rule,
    CASE WHEN m.implemented THEN COALESCE(r.alerts, 0) END                  AS alerts,
    CASE WHEN m.implemented THEN ROUND(COALESCE(r.fraud_amt_caught, 0), 2) END AS fraud_amt_caught,
    ROUND(t.total_fraud_amt, 2)                                             AS total_fraud_amt,
    CASE WHEN m.implemented
         THEN ROUND(100.0 * COALESCE(r.fraud_amt_caught, 0) / t.total_fraud_amt, 2) END AS value_detection_pct,
    getvariable('review_cost')                                              AS review_cost,
    CASE WHEN m.implemented
         THEN ROUND(COALESCE(r.fraud_amt_caught, 0) - COALESCE(r.alerts, 0) * getvariable('review_cost'), 2) END
                                                                            AS net_benefit
FROM metric_rules m
LEFT JOIN per_rule r USING (rule)
CROSS JOIN period_totals t
ORDER BY m.rule LIKE 'any_%', m.rule;

-- name: card_detection
-- A card counts as detected only if an alert landed on one of its fraud rows;
-- an alert on its genuine spending does not count.
WITH per_rule AS (
    SELECT rule, COUNT(DISTINCT card_id) FILTER (WHERE is_fraud = 1) AS cards_detected
    FROM alerts_long
    GROUP BY rule
)
SELECT
    m.rule,
    t.compromised_cards,
    CASE WHEN m.implemented THEN COALESCE(r.cards_detected, 0) END AS cards_detected,
    CASE WHEN m.implemented
         THEN ROUND(100.0 * COALESCE(r.cards_detected, 0) / t.compromised_cards, 2) END AS card_detection_pct
FROM metric_rules m
LEFT JOIN per_rule r USING (rule)
CROSS JOIN period_totals t
ORDER BY m.rule LIKE 'any_%', m.rule;

-- name: loss_before_first_alert
-- For each compromised card: fraud rows and fraud amount strictly before the
-- first fraud row the rule (or set) alerted on. A fraud row at the same second
-- as that first alert counts as caught. A card never alerted on a fraud row
-- loses all of its scored fraud.
WITH fraud_rows AS (
    SELECT card_id, ts, amt FROM scored_flags WHERE is_fraud = 1
),
first_alert AS (
    SELECT rule, card_id, MIN(ts) AS first_alert_ts
    FROM alerts_long
    WHERE is_fraud = 1
    GROUP BY rule, card_id
),
per_card AS (
    SELECT
        m.rule,
        f.card_id,
        ANY_VALUE(a.first_alert_ts) IS NULL AS never_alerted,
        COUNT(*) FILTER (WHERE a.first_alert_ts IS NULL OR f.ts < a.first_alert_ts) AS fraud_txns_before,
        COALESCE(SUM(f.amt) FILTER (WHERE a.first_alert_ts IS NULL OR f.ts < a.first_alert_ts), 0)
            AS fraud_amt_before
    FROM metric_rules m
    CROSS JOIN fraud_rows f
    LEFT JOIN first_alert a ON a.rule = m.rule AND a.card_id = f.card_id
    WHERE m.implemented
    GROUP BY m.rule, f.card_id
)
SELECT
    rule,
    COUNT(*)                                       AS compromised_cards,
    COUNT(*) FILTER (WHERE never_alerted)          AS never_alerted_cards,
    MEDIAN(fraud_txns_before)                      AS median_fraud_txns_before,
    QUANTILE_CONT(fraud_txns_before, 0.9)          AS p90_fraud_txns_before,
    ROUND(MEDIAN(fraud_amt_before), 2)             AS median_fraud_amt_before,
    ROUND(QUANTILE_CONT(fraud_amt_before, 0.9), 2) AS p90_fraud_amt_before,
    ROUND(SUM(fraud_amt_before), 2)                AS total_fraud_amt_before
FROM per_card
GROUP BY rule
ORDER BY rule LIKE 'any_%', rule;

-- name: unique_catches
-- For an ACTIVE rule: rows where it is the only active rule that fired. These
-- are exactly the alerts saved and the fraud lost if the rule were removed
-- (leave-one-out).
-- For a RETIRED or SHADOW rule: rows it hits that no active rule hits, i.e.
-- what it would add if it were made active.
SELECT
    h.rule,
    h.status,
    CASE WHEN COUNT(h.hit) > 0 THEN COUNT(*) FILTER (WHERE h.hit) END                  AS alerts,
    CASE WHEN COUNT(h.hit) > 0 THEN COUNT(*) FILTER (WHERE h.hit AND h.is_fraud = 1) END AS fraud_alerts,
    CASE WHEN COUNT(h.hit) > 0 THEN COUNT(*) FILTER (WHERE h.hit AND other_active = 0) END AS unique_alerts,
    CASE WHEN COUNT(h.hit) > 0
         THEN COUNT(*) FILTER (WHERE h.hit AND other_active = 0 AND h.is_fraud = 1) END AS unique_fraud_catches,
    CASE WHEN COUNT(h.hit) > 0
         THEN ROUND(COALESCE(SUM(h.amt) FILTER (WHERE h.hit AND other_active = 0 AND h.is_fraud = 1), 0), 2) END
                                                                                       AS unique_fraud_amt
FROM (
    SELECT
        h.*,
        r.active_fired - CASE WHEN h.status = 'active' AND h.hit THEN 1 ELSE 0 END AS other_active
    FROM rule_hits_long h
    JOIN txn_rules_fired r USING (trans_num)
) h
GROUP BY h.rule, h.status
ORDER BY h.rule;

-- name: case_volume
SELECT
    c.rule,
    COUNT(*)                                                    AS alerts,
    COUNT(DISTINCT (c.card_id, c.case_start))                   AS cases,
    ROUND(COUNT(*) / ANY_VALUE(t.days), 2)                      AS alerts_per_day,
    ROUND(COUNT(DISTINCT (c.card_id, c.case_start)) / ANY_VALUE(t.days), 2) AS cases_per_day,
    ROUND(COUNT(*) / COUNT(DISTINCT (c.card_id, c.case_start)), 2) AS alerts_per_case
FROM alert_cases c
CROSS JOIN period_totals t
GROUP BY c.rule
ORDER BY c.rule LIKE 'any_%', c.rule;

-- name: first_alert_view
-- For each compromised card, take its first fraud row that any active rule
-- alerted on, and record which active rules fired on it. A high-precision rule
-- with few unique catches can still be the rule that fires first, and its
-- action is then the one the customer experiences.
-- cards_where_rule_set_action: this rule's action was the strongest on that
-- first alert, so it decided the customer's first response (ties all count).
WITH action_rank(action, severity) AS (
    VALUES ('ALERT', 1), ('STEP_UP', 2), ('HOLD_CONFIRM', 3), ('BLOCK', 4)
),
first_alerted AS (
    SELECT card_id, ARG_MIN(trans_num, (ts, trans_num)) AS trans_num
    FROM txn_rules_fired
    WHERE is_fraud = 1 AND active_fired > 0
    GROUP BY card_id
),
first_alert_rules AS (
    SELECT h.trans_num, h.rule, c.action, ar.severity,
           MAX(ar.severity) OVER (PARTITION BY h.trans_num) AS strongest_severity
    FROM first_alerted f
    JOIN rule_hits_long h USING (trans_num)
    JOIN rule_catalogue c USING (rule)
    JOIN action_rank ar ON ar.action = c.action
    WHERE h.hit AND h.status = 'active'
),
detected AS (SELECT COUNT(*) AS cards FROM first_alerted)
SELECT
    a.rule,
    ANY_VALUE(a.action)                                      AS action,
    ANY_VALUE(d.cards)                                       AS cards_detected,
    COUNT(*)                                                 AS cards_where_rule_fired_on_first_alert,
    COUNT(*) FILTER (WHERE r.active_fired = 1)               AS cards_where_only_this_rule_fired,
    COUNT(*) FILTER (WHERE a.severity = a.strongest_severity) AS cards_where_rule_set_action,
    ROUND(100.0 * COUNT(*) / ANY_VALUE(d.cards), 2)          AS pct_of_detected_cards
FROM first_alert_rules a
JOIN txn_rules_fired r USING (trans_num)
CROSS JOIN detected d
GROUP BY a.rule
ORDER BY a.rule;

-- name: action_mix
-- Each alerted transaction gets the strongest action of the active rules that
-- fired. STEP_UP and HOLD_CONFIRM act before the payment completes; ALERT is
-- reviewed afterwards.
WITH action_rank(action, severity) AS (
    VALUES ('ALERT', 1), ('STEP_UP', 2), ('HOLD_CONFIRM', 3), ('BLOCK', 4)
),
strongest AS (
    SELECT h.trans_num, ANY_VALUE(h.amt) AS amt, ANY_VALUE(h.is_fraud) AS is_fraud,
           ARG_MAX(c.action, ar.severity) AS action
    FROM rule_hits_long h
    JOIN rule_catalogue c USING (rule)
    JOIN action_rank ar ON ar.action = c.action
    WHERE h.hit AND h.status = 'active'
    GROUP BY h.trans_num
)
SELECT
    s.action                                                    AS strongest_action,
    COUNT(*)                                                    AS alerts,
    ROUND(COUNT(*) / ANY_VALUE(t.days), 2)                      AS alerts_per_day,
    COUNT(*) FILTER (WHERE s.is_fraud = 1)                      AS fraud_alerts,
    ROUND(100.0 * COUNT(*) FILTER (WHERE s.is_fraud = 1) / COUNT(*), 2) AS precision_pct,
    ROUND(COALESCE(SUM(s.amt) FILTER (WHERE s.is_fraud = 1), 0), 2)     AS fraud_amt,
    ROUND(100.0 * COALESCE(SUM(s.amt) FILTER (WHERE s.is_fraud = 1), 0) / ANY_VALUE(t.total_fraud_amt), 2)
                                                                AS pct_of_total_fraud_amt
FROM strongest s
CROSS JOIN period_totals t
GROUP BY s.action
ORDER BY s.action;

-- name: monthly_active
-- The live rule set month by month: workload against the budget, and drift.
-- Cases are counted in the month their opening alert falls in.
WITH monthly_cases AS (
    SELECT DATE_TRUNC('month', case_start)::DATE AS month, COUNT(DISTINCT (card_id, case_start)) AS cases
    FROM alert_cases
    WHERE rule = 'any_active'
    GROUP BY month
),
monthly AS (
SELECT
    DATE_TRUNC('month', ts)::DATE                                       AS month,
    COUNT(DISTINCT CAST(ts AS DATE))                                    AS days,
    COUNT(*)                                                            AS txns,
    SUM(is_fraud)                                                       AS fraud_txns,
    ROUND(100.0 * AVG(is_fraud), 3)                                     AS fraud_rate_pct,
    COUNT(*) FILTER (WHERE active_fired > 0)                            AS alerts,
    ROUND(COUNT(*) FILTER (WHERE active_fired > 0) / COUNT(DISTINCT CAST(ts AS DATE)), 2) AS alerts_per_day,
    COUNT(*) FILTER (WHERE active_fired > 0 AND is_fraud = 1)           AS fraud_alerts,
    ROUND(100.0 * COUNT(*) FILTER (WHERE active_fired > 0 AND is_fraud = 1)
        / NULLIF(COUNT(*) FILTER (WHERE active_fired > 0), 0), 2)       AS precision_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE active_fired > 0 AND is_fraud = 1) / NULLIF(SUM(is_fraud), 0), 2)
                                                                        AS txn_recall_pct,
    ROUND(100.0 * COALESCE(SUM(amt) FILTER (WHERE active_fired > 0 AND is_fraud = 1), 0)
        / NULLIF(SUM(amt) FILTER (WHERE is_fraud = 1), 0), 2)           AS value_detection_pct
FROM txn_rules_fired
GROUP BY month
)
SELECT
    m.*,
    COALESCE(c.cases, 0)                                AS cases,
    ROUND(COALESCE(c.cases, 0) / m.days, 2)             AS cases_per_day
FROM monthly m
LEFT JOIN monthly_cases c USING (month)
ORDER BY m.month;
