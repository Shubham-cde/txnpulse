-- Builds the R8 merchant risk list from TRAINING rows only.
-- Expects table raw_train from sql/00_load.sql. src/build_risk_list.py runs it
-- and writes the result to rules/risk_lists/merchant_risk_v1.csv.
--
-- Criteria (list v1):
--   * minimum volume: >= 500 train transactions and >= 10 fraud transactions,
--     so a rate is not driven by a handful of rows
--   * tier by fraud rate as a multiple of the train base rate (0.579%):
--       very_high: >= 4.0x  -> action BLOCK
--       high:      >= 3.5x  -> action HOLD_CONFIRM
-- The multiples were set so the list stays small (about 26 alerts/day on train
-- volume); merchant-level fraud in this data is mostly category mix.

-- name: merchant_risk_list
WITH base AS (
    SELECT AVG(is_fraud) AS base_rate, MAX(ts) AS train_end FROM raw_train
),
per_merchant AS (
    SELECT
        merchant,
        COUNT(*)      AS train_txns,
        SUM(is_fraud) AS train_fraud_txns,
        AVG(is_fraud) AS fraud_rate
    FROM raw_train
    GROUP BY merchant
    HAVING COUNT(*) >= 500 AND SUM(is_fraud) >= 10
)
SELECT
    'v1'                                      AS list_version,
    m.merchant,
    CASE WHEN m.fraud_rate >= 4.0 * b.base_rate THEN 'very_high' ELSE 'high' END AS tier,
    m.train_txns,
    m.train_fraud_txns,
    ROUND(100.0 * m.fraud_rate, 3)            AS train_fraud_rate_pct,
    ROUND(m.fraud_rate / b.base_rate, 2)      AS rate_multiple,
    'fraudTrain.csv'                          AS built_from,
    CAST(b.train_end AS DATE)                 AS data_through
FROM per_merchant m
CROSS JOIN base b
WHERE m.fraud_rate >= 3.5 * b.base_rate
ORDER BY m.fraud_rate DESC;
