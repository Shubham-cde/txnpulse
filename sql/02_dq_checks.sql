-- Data-quality checks on both raw files.
-- Expects tables raw_train and raw_test created by sql/00_load.sql.
-- Each "-- name:" block is saved to outputs/dq/<name>.csv by src/profile_data.py.

CREATE OR REPLACE VIEW raw_both AS
SELECT 'train' AS file, * FROM raw_train
UNION ALL
SELECT 'test' AS file, * FROM raw_test;

-- name: dq_row_counts
SELECT
    file,
    COUNT(*)                        AS row_count,
    SUM(is_fraud)                   AS fraud_count,
    ROUND(100.0 * AVG(is_fraud), 4) AS fraud_rate_pct
FROM raw_both
GROUP BY file
ORDER BY file DESC;

-- name: dq_null_counts
UNPIVOT (
    SELECT file, SUM(CAST(COLUMNS(* EXCLUDE (file)) IS NULL AS BIGINT))
    FROM raw_both
    GROUP BY file
)
ON COLUMNS(* EXCLUDE (file))
INTO NAME column_name VALUE null_count
ORDER BY file DESC, column_name;

-- name: dq_date_ranges
SELECT
    file,
    MIN(ts) AS min_ts,
    MAX(ts) AS max_ts,
    COUNT(DISTINCT CAST(ts AS DATE)) AS distinct_days,
    DATE_DIFF('day', MIN(ts), MAX(ts)) + 1 AS calendar_days
FROM raw_both
GROUP BY file
ORDER BY file DESC;

-- name: dq_period_overlap
SELECT
    (SELECT MAX(ts) FROM raw_train) AS train_max_ts,
    (SELECT MIN(ts) FROM raw_test)  AS test_min_ts,
    (SELECT MAX(ts) FROM raw_train) < (SELECT MIN(ts) FROM raw_test) AS no_overlap;

-- name: dq_duplicate_trans_num
SELECT
    'within_train' AS scope,
    COUNT(*) - COUNT(DISTINCT trans_num) AS duplicate_count
FROM raw_train
UNION ALL
SELECT
    'within_test',
    COUNT(*) - COUNT(DISTINCT trans_num)
FROM raw_test
UNION ALL
SELECT
    'train_and_test',
    COUNT(*)
FROM raw_train
JOIN raw_test USING (trans_num);

-- name: dq_duplicate_card_ts_amt
-- Same card, same second, same amount. Could be genuine (a retried payment)
-- or a load duplicate; either way R1 counts each row, so it is worth knowing.
WITH duplicate_groups AS (
    SELECT file, card_id, ts, amt, COUNT(*) AS rows_in_group, SUM(is_fraud) AS fraud_in_group
    FROM raw_both
    GROUP BY file, card_id, ts, amt
    HAVING COUNT(*) > 1
)
SELECT
    f.file,
    COUNT(d.file)                       AS duplicate_groups,
    COALESCE(SUM(d.rows_in_group), 0)   AS rows_involved,
    COALESCE(SUM(d.fraud_in_group), 0)  AS fraud_rows_involved
FROM (VALUES ('train'), ('test')) AS f(file)
LEFT JOIN duplicate_groups d USING (file)
GROUP BY f.file
ORDER BY f.file DESC;

-- name: dq_amount_checks
SELECT
    file,
    SUM(CASE WHEN amt = 0 THEN 1 ELSE 0 END) AS zero_amount_rows,
    SUM(CASE WHEN amt < 0 THEN 1 ELSE 0 END) AS negative_amount_rows,
    MIN(amt)                                 AS min_amt,
    MEDIAN(amt)                              AS median_amt,
    MAX(amt)                                 AS max_amt
FROM raw_both
GROUP BY file
ORDER BY file DESC;

-- name: dq_distinct_entities
SELECT
    file,
    COUNT(DISTINCT card_id)  AS distinct_cards,
    COUNT(DISTINCT merchant) AS distinct_merchants,
    COUNT(DISTINCT category) AS distinct_categories,
    COUNT(DISTINCT CASE WHEN is_fraud = 1 THEN card_id END) AS cards_with_fraud
FROM raw_both
GROUP BY file
ORDER BY file DESC;

-- name: dq_test_cards_in_train
SELECT
    COUNT(*)                                        AS test_cards,
    SUM(CASE WHEN in_train THEN 1 ELSE 0 END)       AS also_in_train,
    SUM(CASE WHEN NOT in_train THEN 1 ELSE 0 END)   AS new_in_test,
    SUM(CASE WHEN has_test_fraud AND NOT in_train THEN 1 ELSE 0 END) AS new_cards_with_fraud
FROM (
    SELECT
        t.card_id,
        BOOL_OR(t.is_fraud = 1) AS has_test_fraud,
        t.card_id IN (SELECT card_id FROM raw_train) AS in_train
    FROM raw_test t
    GROUP BY t.card_id
);

-- name: dq_unix_time_vs_ts
-- unix_time does not match ts. The raw offset is 2556 or 2557 days, which
-- fits ts moved back 7 calendar years; this query tests that explanation.
SELECT
    file,
    CASE
        WHEN unix_time = EPOCH(ts) THEN 'matches ts'
        WHEN unix_time = EPOCH(ts - INTERVAL 7 YEAR) THEN 'ts minus 7 years'
        WHEN unix_time = EPOCH(ts - INTERVAL 7 YEAR) + 86400 THEN 'ts minus 7 years, plus 1 day'
        ELSE 'other'
    END                     AS relationship,
    COUNT(*)                AS row_count,
    MIN(ts)                 AS min_ts,
    MAX(ts)                 AS max_ts
FROM raw_both
GROUP BY file, relationship
ORDER BY file DESC, row_count DESC;

-- name: dq_value_ranges
SELECT
    file,
    SUM(CASE WHEN lat NOT BETWEEN -90 AND 90 OR long NOT BETWEEN -180 AND 180 THEN 1 ELSE 0 END)
        AS bad_customer_coords,
    SUM(CASE WHEN merch_lat NOT BETWEEN -90 AND 90 OR merch_long NOT BETWEEN -180 AND 180 THEN 1 ELSE 0 END)
        AS bad_merchant_coords,
    SUM(CASE WHEN is_fraud NOT IN (0, 1) THEN 1 ELSE 0 END) AS bad_label_values,
    SUM(CASE WHEN merchant NOT LIKE 'fraud\_%' ESCAPE '\' THEN 1 ELSE 0 END) AS merchant_without_prefix
FROM raw_both
GROUP BY file
ORDER BY file DESC;
