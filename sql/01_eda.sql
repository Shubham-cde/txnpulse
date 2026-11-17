-- Exploratory analysis on the TRAINING file only. Rule thresholds for R4 and R5
-- come from here, so fraudTest must never be read in this file.
-- Expects table raw_train created by sql/00_load.sql.

-- haversine_km comes from sql/05_macros.sql (loaded by src/db.py connect()).

-- Bands are closed on the left: [lower, upper).
CREATE OR REPLACE MACRO amount_band(a) AS
    CASE
        WHEN a < 10   THEN '01: <10'
        WHEN a < 50   THEN '02: 10-50'
        WHEN a < 100  THEN '03: 50-100'
        WHEN a < 200  THEN '04: 100-200'
        WHEN a < 300  THEN '05: 200-300'
        WHEN a < 500  THEN '06: 300-500'
        WHEN a < 750  THEN '07: 500-750'
        WHEN a < 1000 THEN '08: 750-1000'
        WHEN a < 1500 THEN '09: 1000-1500'
        ELSE               '10: 1500+'
    END;

CREATE OR REPLACE TABLE eda_txn AS
SELECT
    *,
    HOUR(ts) AS hour_of_day,
    amount_band(amt) AS amt_band,
    haversine_km(lat, long, merch_lat, merch_long) AS distance_km
FROM raw_train;

-- name: fraud_by_hour
SELECT
    hour_of_day,
    COUNT(*)                                          AS txns,
    SUM(is_fraud)                                     AS fraud_txns,
    ROUND(100.0 * AVG(is_fraud), 3)                   AS fraud_rate_pct,
    ROUND(SUM(CASE WHEN is_fraud = 1 THEN amt END), 2) AS fraud_amt,
    ROUND(MEDIAN(CASE WHEN is_fraud = 1 THEN amt END), 2) AS median_fraud_amt
FROM eda_txn
GROUP BY hour_of_day
ORDER BY hour_of_day;

-- name: fraud_by_category
SELECT
    category,
    COUNT(*)                                               AS txns,
    SUM(is_fraud)                                          AS fraud_txns,
    ROUND(100.0 * AVG(is_fraud), 3)                        AS fraud_rate_pct,
    ROUND(100.0 * SUM(is_fraud) / SUM(SUM(is_fraud)) OVER (), 2) AS share_of_fraud_pct,
    ROUND(SUM(CASE WHEN is_fraud = 1 THEN amt END), 2)      AS fraud_amt,
    ROUND(MEDIAN(CASE WHEN is_fraud = 1 THEN amt END), 2)   AS median_fraud_amt,
    ROUND(MEDIAN(CASE WHEN is_fraud = 0 THEN amt END), 2)   AS median_normal_amt
FROM eda_txn
GROUP BY category
ORDER BY fraud_rate_pct DESC;

-- name: fraud_by_amount_band
SELECT
    amt_band,
    COUNT(*)                                          AS txns,
    SUM(is_fraud)                                     AS fraud_txns,
    ROUND(100.0 * AVG(is_fraud), 3)                   AS fraud_rate_pct,
    ROUND(100.0 * SUM(is_fraud) / SUM(SUM(is_fraud)) OVER (), 2) AS share_of_fraud_pct,
    ROUND(SUM(CASE WHEN is_fraud = 1 THEN amt END), 2) AS fraud_amt
FROM eda_txn
GROUP BY amt_band
ORDER BY amt_band;

-- name: fraud_by_category_and_amount_band
-- Input for choosing R4's category list and amount threshold.
SELECT
    category,
    amt_band,
    COUNT(*)                        AS txns,
    SUM(is_fraud)                   AS fraud_txns,
    ROUND(100.0 * AVG(is_fraud), 3) AS fraud_rate_pct
FROM eda_txn
GROUP BY category, amt_band
ORDER BY category, amt_band;

-- name: fraud_by_month
SELECT
    DATE_TRUNC('month', ts)::DATE   AS month,
    COUNT(*)                        AS txns,
    SUM(is_fraud)                   AS fraud_txns,
    ROUND(100.0 * AVG(is_fraud), 3) AS fraud_rate_pct
FROM eda_txn
GROUP BY month
ORDER BY month;

-- name: fraud_card_profile
-- One row per card that had at least one fraud transaction.
-- Card numbers are masked to the last 4 digits; the full number is not needed here.
WITH card_rows AS (
    SELECT
        card_id, ts, amt, is_fraud,
        MIN(CASE WHEN is_fraud = 1 THEN ts END) OVER (PARTITION BY card_id) AS first_fraud_ts
    FROM eda_txn
)
SELECT
    'XXXX' || RIGHT(card_id, 4)                         AS card_masked,
    COUNT(*) FILTER (WHERE is_fraud = 1)                AS fraud_txns,
    COUNT(*) FILTER (WHERE is_fraud = 0)                AS normal_txns,
    MIN(first_fraud_ts)                                 AS first_fraud_ts,
    MAX(ts) FILTER (WHERE is_fraud = 1)                 AS last_fraud_ts,
    ROUND(DATE_DIFF('minute', MIN(first_fraud_ts),
        MAX(ts) FILTER (WHERE is_fraud = 1)) / 60.0, 2) AS fraud_span_hours,
    ROUND(SUM(amt) FILTER (WHERE is_fraud = 1), 2)      AS fraud_amt,
    COUNT(*) FILTER (WHERE is_fraud = 0 AND ts < first_fraud_ts) AS normal_txns_before_first_fraud
FROM card_rows
WHERE first_fraud_ts IS NOT NULL
GROUP BY card_id
ORDER BY fraud_amt DESC;

-- name: fraud_card_summary
WITH per_card AS (
    SELECT
        card_id,
        COUNT(*) FILTER (WHERE is_fraud = 1)           AS fraud_txns,
        DATE_DIFF('minute',
            MIN(ts) FILTER (WHERE is_fraud = 1),
            MAX(ts) FILTER (WHERE is_fraud = 1)) / 60.0 AS fraud_span_hours,
        SUM(amt) FILTER (WHERE is_fraud = 1)           AS fraud_amt
    FROM eda_txn
    GROUP BY card_id
    HAVING SUM(is_fraud) > 0
)
SELECT
    'fraud_txns_per_card' AS measure,
    MIN(fraud_txns) AS min, QUANTILE_CONT(fraud_txns, 0.25) AS p25, MEDIAN(fraud_txns) AS p50,
    QUANTILE_CONT(fraud_txns, 0.75) AS p75, QUANTILE_CONT(fraud_txns, 0.90) AS p90, MAX(fraud_txns) AS max
FROM per_card
UNION ALL
SELECT
    'fraud_span_hours',
    MIN(fraud_span_hours), QUANTILE_CONT(fraud_span_hours, 0.25), MEDIAN(fraud_span_hours),
    QUANTILE_CONT(fraud_span_hours, 0.75), QUANTILE_CONT(fraud_span_hours, 0.90), MAX(fraud_span_hours)
FROM per_card
UNION ALL
SELECT
    'fraud_amt_per_card',
    MIN(fraud_amt), QUANTILE_CONT(fraud_amt, 0.25), MEDIAN(fraud_amt),
    QUANTILE_CONT(fraud_amt, 0.75), QUANTILE_CONT(fraud_amt, 0.90), MAX(fraud_amt)
FROM per_card;

-- name: fraud_gap_minutes
-- Minutes between consecutive fraud transactions on the same card. Informs
-- whether R1's 60-minute window matches how fraud actually arrives.
WITH fraud_rows AS (
    SELECT
        card_id,
        DATE_DIFF('second', LAG(ts) OVER (PARTITION BY card_id ORDER BY ts), ts) / 60.0 AS gap_minutes
    FROM eda_txn
    WHERE is_fraud = 1
)
SELECT
    COUNT(gap_minutes)                    AS gaps,
    QUANTILE_CONT(gap_minutes, 0.10)      AS p10,
    QUANTILE_CONT(gap_minutes, 0.25)      AS p25,
    MEDIAN(gap_minutes)                   AS p50,
    QUANTILE_CONT(gap_minutes, 0.75)      AS p75,
    QUANTILE_CONT(gap_minutes, 0.90)      AS p90,
    ROUND(100.0 * AVG(CASE WHEN gap_minutes <= 60 THEN 1 ELSE 0 END), 2) AS pct_within_60_min
FROM fraud_rows;

-- name: distance_by_label
SELECT
    CASE WHEN is_fraud = 1 THEN 'fraud' ELSE 'normal' END AS label,
    COUNT(*)                                  AS txns,
    ROUND(MIN(distance_km), 2)                AS min_km,
    ROUND(QUANTILE_CONT(distance_km, 0.10), 2) AS p10_km,
    ROUND(QUANTILE_CONT(distance_km, 0.25), 2) AS p25_km,
    ROUND(MEDIAN(distance_km), 2)             AS p50_km,
    ROUND(QUANTILE_CONT(distance_km, 0.75), 2) AS p75_km,
    ROUND(QUANTILE_CONT(distance_km, 0.90), 2) AS p90_km,
    ROUND(QUANTILE_CONT(distance_km, 0.99), 2) AS p99_km,
    ROUND(MAX(distance_km), 2)                AS max_km
FROM eda_txn
GROUP BY label
ORDER BY label;

-- name: fraud_by_distance_band
SELECT
    CAST(FLOOR(distance_km / 25) * 25 AS INTEGER)   AS distance_band_start_km,
    COUNT(*)                                        AS txns,
    SUM(is_fraud)                                   AS fraud_txns,
    ROUND(100.0 * AVG(is_fraud), 3)                 AS fraud_rate_pct
FROM eda_txn
GROUP BY distance_band_start_km
ORDER BY distance_band_start_km;

-- name: r4_option_comparison
-- Candidate R4 designs scored on exact amt > threshold (not bands).
-- Option D is the chosen design: per-category thresholds, no upper cap.
WITH options(option_id, category, min_amt_exclusive) AS (
    VALUES
        ('A: 3 cats > 500', 'shopping_net', 500), ('A: 3 cats > 500', 'misc_net', 500),
        ('A: 3 cats > 500', 'shopping_pos', 500),
        ('B: 3 cats > 750', 'shopping_net', 750), ('B: 3 cats > 750', 'misc_net', 750),
        ('B: 3 cats > 750', 'shopping_pos', 750),
        ('C: 4 cats > 300', 'shopping_net', 300), ('C: 4 cats > 300', 'misc_net', 300),
        ('C: 4 cats > 300', 'shopping_pos', 300), ('C: 4 cats > 300', 'grocery_pos', 300),
        ('D: 3 cats > 500, grocery_pos > 300', 'shopping_net', 500),
        ('D: 3 cats > 500, grocery_pos > 300', 'misc_net', 500),
        ('D: 3 cats > 500, grocery_pos > 300', 'shopping_pos', 500),
        ('D: 3 cats > 500, grocery_pos > 300', 'grocery_pos', 300)
),
totals AS (
    SELECT
        SUM(is_fraud)                                   AS total_fraud_txns,
        SUM(CASE WHEN is_fraud = 1 THEN amt ELSE 0 END) AS total_fraud_amt,
        COUNT(DISTINCT CAST(ts AS DATE))                AS days
    FROM eda_txn
),
hits AS (
    SELECT o.option_id, e.is_fraud, e.amt
    FROM eda_txn e
    JOIN options o ON e.category = o.category AND e.amt > o.min_amt_exclusive
)
SELECT
    h.option_id,
    COUNT(*)                                                       AS alerts,
    ROUND(COUNT(*) / ANY_VALUE(t.days), 1)                         AS alerts_per_day,
    SUM(h.is_fraud)                                                AS fraud_alerts,
    ROUND(100.0 * SUM(h.is_fraud) / COUNT(*), 1)                   AS precision_pct,
    ROUND((COUNT(*) - SUM(h.is_fraud)) / SUM(h.is_fraud), 2)       AS fp_per_fraud,
    ROUND(100.0 * SUM(h.is_fraud) / ANY_VALUE(t.total_fraud_txns), 1) AS txn_recall_pct,
    ROUND(100.0 * SUM(CASE WHEN h.is_fraud = 1 THEN h.amt ELSE 0 END)
        / ANY_VALUE(t.total_fraud_amt), 1)                         AS value_detection_pct
FROM hits h
CROSS JOIN totals t
GROUP BY h.option_id
ORDER BY h.option_id;
