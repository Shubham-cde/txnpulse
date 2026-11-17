-- Threshold sensitivity on TRAIN only. src/run_rules.py runs this file only for
-- --period train; thresholds must never be chosen from test rows.
-- Expects table scored_flags from sql/20_rule_performance.sql.
-- These queries report alternatives; they do not change the live rules in sql/10.

-- name: r6_sensitivity
-- N = minimum prior transactions on the card, Y = amount must exceed this.
-- Live starting values: N = 10, Y = 300.
WITH grid(min_prior_txns, min_amt) AS (
    SELECT n, y
    FROM (VALUES (5), (10), (20)) AS ns(n)
    CROSS JOIN (VALUES (200.0), (300.0), (500.0)) AS ys(y)
),
period AS (
    SELECT
        COUNT(DISTINCT CAST(ts AS DATE)) AS days,
        SUM(is_fraud)                    AS total_fraud_txns
    FROM scored_flags
),
first_visits AS (
    SELECT prior_txn_count, amt, is_fraud
    FROM scored_flags
    WHERE first_visit
)
SELECT
    g.min_prior_txns,
    g.min_amt,
    g.min_prior_txns = 10 AND g.min_amt = 300                       AS is_live_setting,
    COUNT(v.amt)                                                    AS alerts,
    ROUND(COUNT(v.amt) / ANY_VALUE(p.days), 2)                      AS alerts_per_day,
    COALESCE(SUM(v.is_fraud), 0)                                    AS fraud_alerts,
    ROUND(100.0 * SUM(v.is_fraud) / NULLIF(COUNT(v.amt), 0), 2)     AS precision_pct,
    ROUND(100.0 * COALESCE(SUM(v.is_fraud), 0) / ANY_VALUE(p.total_fraud_txns), 2) AS txn_recall_pct
FROM grid g
CROSS JOIN period p
LEFT JOIN first_visits v
    ON v.prior_txn_count >= g.min_prior_txns
   AND v.amt > g.min_amt
GROUP BY g.min_prior_txns, g.min_amt
ORDER BY g.min_prior_txns, g.min_amt;
