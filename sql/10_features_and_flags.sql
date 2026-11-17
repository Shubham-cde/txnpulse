-- Rule features and flags.
-- Input:  table or view `txn` (columns from sql/00_load.sql, plus is_scored).
-- Output: table `flags`, one row per txn row, one boolean column per rule.
-- Needs haversine_km from sql/05_macros.sql (loaded by src/db.py connect()).
--
-- Past-only features: every window ends at the current row, and averages
-- exclude the current transaction. ROWS windows order by (ts, trans_num) so
-- ties on the same second have a fixed order.
--
-- Every flag is COALESCEd to FALSE: a comparison against a missing value
-- (no history, category not in a list) is NULL, and NULL must mean "did not fire".
--
-- Only rule flags may be named r<digit>_...; sql/20 treats every such column as a rule.


-- R7 baseline: one row per card per active calendar day of ts.
CREATE OR REPLACE TABLE card_daily_spend AS
SELECT
    card_id,
    CAST(ts AS DATE) AS txn_date,
    SUM(amt)         AS day_spend
FROM txn
GROUP BY card_id, txn_date;

-- "1 PRECEDING" keeps the current day out of its own baseline. Inactive days
-- have no row, so the 30 days are the card's last 30 days with spend.
CREATE OR REPLACE TABLE card_daily_baseline AS
SELECT
    card_id,
    txn_date,
    AVG(day_spend) OVER prev_30_active_days AS baseline_daily_avg,
    COUNT(*)       OVER prev_30_active_days AS prior_active_days
FROM card_daily_spend
WINDOW prev_30_active_days AS (
    PARTITION BY card_id ORDER BY txn_date
    ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
);


CREATE OR REPLACE TABLE features AS
SELECT
    t.*,
    HOUR(t.ts) AS hour_of_day,

    -- R1: RANGE counts every row whose ts is in [ts - 60 min, ts], including
    -- the current row and any rows at the same second.
    COUNT(*) OVER (
        PARTITION BY t.card_id ORDER BY t.ts
        RANGE BETWEEN INTERVAL 60 MINUTES PRECEDING AND CURRENT ROW
    ) AS txn_count_60m,

    -- R2, R6: history strictly before the current row.
    COUNT(*) OVER (
        PARTITION BY t.card_id ORDER BY t.ts, t.trans_num
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS prior_txn_count,
    AVG(t.amt) OVER (
        PARTITION BY t.card_id ORDER BY t.ts, t.trans_num
        ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
    ) AS avg_amt_prev30,

    -- R5
    haversine_km(t.lat, t.long, t.merch_lat, t.merch_long) AS distance_km,

    -- R6: TRUE only for the card's earliest row at this merchant.
    ROW_NUMBER() OVER (
        PARTITION BY t.card_id, t.merchant ORDER BY t.ts, t.trans_num
    ) = 1 AS first_visit,

    -- R7: spend in [ts - 24 h, ts], including the current row and same-second rows.
    SUM(t.amt) OVER (
        PARTITION BY t.card_id ORDER BY t.ts
        RANGE BETWEEN INTERVAL 24 HOURS PRECEDING AND CURRENT ROW
    ) AS spend_24h,
    b.baseline_daily_avg,
    b.prior_active_days
FROM txn t
LEFT JOIN card_daily_baseline b
    ON b.card_id = t.card_id
   AND b.txn_date = CAST(t.ts AS DATE);


-- R4 thresholds, one per category. Fraud in grocery_pos sits at $200-500 in
-- train, while the online and shopping categories sit at $500+, so one shared
-- threshold would either miss grocery_pos or flood the other three.
-- No upper caps: train has no fraud above $1,500, but that is a simulator
-- artifact, not fraudster behaviour.
CREATE OR REPLACE TABLE r4_category_threshold(category, min_amt) AS
VALUES
    ('shopping_net', 500.0),
    ('misc_net',     500.0),
    ('shopping_pos', 500.0),
    ('grocery_pos',  300.0);


CREATE OR REPLACE TABLE flags AS
SELECT
    f.*,

    -- R1 Card velocity. Action: ALERT.
    COALESCE(f.txn_count_60m >= 5, FALSE) AS r1_velocity,

    -- R2 Amount spike. Action: STEP_UP.
    -- Known gap: a card's first-ever transaction can never fire (no history).
    COALESCE(f.prior_txn_count >= 1 AND f.amt > 5 * f.avg_amt_prev30, FALSE) AS r2_amount_spike,

    -- R3 Late-night high value. Action: HOLD_CONFIRM.
    COALESCE((f.hour_of_day >= 22 OR f.hour_of_day < 4) AND f.amt > 500, FALSE) AS r3_late_night_high_value,

    -- R4 Risky category + amount. Action: ALERT.
    -- Categories missing from the lookup get NULL min_amt and do not fire.
    COALESCE(f.amt > r4.min_amt, FALSE) AS r4_risky_category_amount,

    -- R5 Distance anomaly. Action: ALERT.
    -- Phase 0 found no distance signal; kept so Phase 3 can retire it on evidence.
    COALESCE(f.distance_km > 100, FALSE) AS r5_distance_anomaly,

    -- R6 New merchant + high amount. Action: STEP_UP.
    -- Starting values N = 10 prior txns, Y = $300; sensitivity in sql/40.
    -- N keeps brand-new cards out: every merchant is "new" to them.
    COALESCE(f.first_visit AND f.prior_txn_count >= 10 AND f.amt > 300, FALSE) AS r6_new_merchant_high_amount,

    -- R7 24-hour spend burst. Action: HOLD_CONFIRM.
    -- Starting value: at least 7 prior active days, so the baseline is not one
    -- or two days of spend.
    COALESCE(f.prior_active_days >= 7 AND f.spend_24h > 3 * f.baseline_daily_avg, FALSE) AS r7_spend_burst_24h
FROM features f
LEFT JOIN r4_category_threshold r4 USING (category);
