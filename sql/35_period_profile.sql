-- Descriptive profile of where fraud sits in the scored period. Runs for both
-- periods so PVT can explain drift. It describes the data; it never feeds back
-- into thresholds (rule set v2 is frozen).
-- Expects table scored_flags from sql/20.

-- name: profile_fraud_by_category
SELECT
    category,
    COUNT(*)                                                        AS txns,
    SUM(is_fraud)                                                   AS fraud_txns,
    ROUND(100.0 * AVG(is_fraud), 3)                                 AS fraud_rate_pct,
    ROUND(100.0 * SUM(is_fraud) / SUM(SUM(is_fraud)) OVER (), 2)    AS share_of_fraud_pct,
    ROUND(MEDIAN(amt) FILTER (WHERE is_fraud = 1), 2)               AS median_fraud_amt
FROM scored_flags
GROUP BY category
ORDER BY fraud_txns DESC;

-- name: profile_fraud_by_hour_window
SELECT
    CASE WHEN hour_of_day >= 22 OR hour_of_day < 4 THEN '22:00-03:59' ELSE '04:00-21:59' END AS hour_window,
    COUNT(*)                                                        AS txns,
    SUM(is_fraud)                                                   AS fraud_txns,
    ROUND(100.0 * AVG(is_fraud), 3)                                 AS fraud_rate_pct,
    ROUND(100.0 * SUM(is_fraud) / SUM(SUM(is_fraud)) OVER (), 2)    AS share_of_fraud_pct
FROM scored_flags
GROUP BY hour_window
ORDER BY hour_window;

-- name: profile_fraud_by_amount_band
SELECT
    amount_band(amt)                                                AS amt_band,
    COUNT(*)                                                        AS txns,
    SUM(is_fraud)                                                   AS fraud_txns,
    ROUND(100.0 * AVG(is_fraud), 3)                                 AS fraud_rate_pct,
    ROUND(100.0 * SUM(is_fraud) / SUM(SUM(is_fraud)) OVER (), 2)    AS share_of_fraud_pct
FROM scored_flags
GROUP BY amt_band
ORDER BY amt_band;

-- name: profile_fraud_per_card
WITH per_card AS (
    SELECT
        card_id,
        COUNT(*)                                       AS fraud_txns,
        DATE_DIFF('minute', MIN(ts), MAX(ts)) / 60.0   AS fraud_span_hours,
        SUM(amt)                                       AS fraud_amt
    FROM scored_flags
    WHERE is_fraud = 1
    GROUP BY card_id
)
SELECT
    COUNT(*)                                 AS compromised_cards,
    MEDIAN(fraud_txns)                       AS median_fraud_txns,
    QUANTILE_CONT(fraud_txns, 0.9)           AS p90_fraud_txns,
    ROUND(MEDIAN(fraud_span_hours), 2)       AS median_span_hours,
    ROUND(MEDIAN(fraud_amt), 2)              AS median_fraud_amt,
    ROUND(QUANTILE_CONT(fraud_amt, 0.9), 2)  AS p90_fraud_amt
FROM per_card;

-- name: profile_period
SELECT
    COUNT(*)                                        AS txns,
    COUNT(DISTINCT CAST(ts AS DATE))                AS days,
    ROUND(COUNT(*) / COUNT(DISTINCT CAST(ts AS DATE)), 1) AS txns_per_day,
    SUM(is_fraud)                                   AS fraud_txns,
    ROUND(100.0 * AVG(is_fraud), 4)                 AS fraud_rate_pct,
    COUNT(*) - SUM(is_fraud)                        AS genuine_txns,
    ROUND(SUM(amt) FILTER (WHERE is_fraud = 1), 2)  AS fraud_amt
FROM scored_flags;

-- name: profile_first_visit
-- How often a scored transaction is the card's first at that merchant. In the
-- test period cards carry their training history, so first visits get rarer.
SELECT
    COUNT(*)                                                          AS txns,
    COUNT(*) FILTER (WHERE first_visit)                               AS first_visit_txns,
    ROUND(100.0 * COUNT(*) FILTER (WHERE first_visit) / COUNT(*), 2)  AS first_visit_pct,
    SUM(is_fraud)                                                     AS fraud_txns,
    COUNT(*) FILTER (WHERE first_visit AND is_fraud = 1)              AS fraud_first_visit_txns,
    ROUND(100.0 * COUNT(*) FILTER (WHERE first_visit AND is_fraud = 1) / SUM(is_fraud), 2)
                                                                      AS fraud_first_visit_pct,
    ROUND(MEDIAN(prior_txn_count), 0)                                 AS median_prior_txns
FROM scored_flags;
