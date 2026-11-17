-- R8 risk-list hit. Runs after sql/10, only for the test period (and in UAT):
-- the list is built from train labels, so scoring train with it would be
-- in-sample. Placeholder filled by src/db.py: {risk_list_csv}
-- Adds r8_risk_list_hit, risk_list_tier and risk_list_version to flags.

CREATE OR REPLACE TABLE merchant_risk_list AS
SELECT merchant, tier, list_version
FROM read_csv('{risk_list_csv}', header = true, columns = {
    'list_version': 'VARCHAR', 'merchant': 'VARCHAR', 'tier': 'VARCHAR',
    'train_txns': 'BIGINT', 'train_fraud_txns': 'BIGINT', 'train_fraud_rate_pct': 'DOUBLE',
    'rate_multiple': 'DOUBLE', 'built_from': 'VARCHAR', 'data_through': 'DATE'
});

-- R8 v1.0. Action by tier: very_high -> BLOCK, high -> HOLD_CONFIRM.
-- Status shadow (rule_catalogue): measured on test, does not alert.
CREATE OR REPLACE TABLE flags_with_r8 AS
SELECT
    f.*,
    l.tier IS NOT NULL AS r8_risk_list_hit,
    l.tier             AS risk_list_tier,
    l.list_version     AS risk_list_version
FROM flags f
LEFT JOIN merchant_risk_list l USING (merchant);

DROP TABLE flags;
ALTER TABLE flags_with_r8 RENAME TO flags;

-- name: r8_by_tier
WITH totals AS (
    SELECT COUNT(DISTINCT CAST(ts AS DATE)) AS days, SUM(is_fraud) AS total_fraud_txns
    FROM flags WHERE is_scored
)
SELECT
    COALESCE(risk_list_tier, 'not listed')                     AS tier,
    COUNT(*)                                                   AS txns,
    ROUND(COUNT(*) / ANY_VALUE(t.days), 2)                     AS txns_per_day,
    SUM(is_fraud)                                              AS fraud_txns,
    ROUND(100.0 * SUM(is_fraud) / COUNT(*), 3)                 AS precision_pct,
    ROUND(100.0 * SUM(is_fraud) / ANY_VALUE(t.total_fraud_txns), 2) AS txn_recall_pct
FROM flags
CROSS JOIN totals t
WHERE is_scored
GROUP BY tier
ORDER BY tier;
