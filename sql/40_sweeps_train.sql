-- Threshold sweeps on TRAIN only. src/run_rules.py runs this file only for
-- --period train; thresholds must never be chosen from test rows.
-- Expects tables flags (sql/10) and scored_flags (sql/20).
-- Sweeps report alternatives; they do not change the live rules in sql/10.
-- Every grid includes the v1 setting so v1 results stay reproducible after
-- the live rules change.

-- Extra window features only the sweeps need. Same-second rows are handled
-- as in sql/10 (EXCLUDE TIES plus earlier peers in trans_num order).
CREATE OR REPLACE TABLE sweep_base AS
SELECT
    f.*,
    COUNT(*) OVER (PARTITION BY card_id ORDER BY ts
        RANGE BETWEEN INTERVAL 120 MINUTES PRECEDING AND CURRENT ROW EXCLUDE TIES)
    + COUNT(*) OVER (PARTITION BY card_id, ts ORDER BY trans_num
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS txn_count_120m,
    COUNT(*) OVER (PARTITION BY card_id ORDER BY ts
        RANGE BETWEEN INTERVAL 180 MINUTES PRECEDING AND CURRENT ROW EXCLUDE TIES)
    + COUNT(*) OVER (PARTITION BY card_id, ts ORDER BY trans_num
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS txn_count_180m
FROM flags f
WHERE f.is_scored;

CREATE OR REPLACE TABLE sweep_totals AS
SELECT
    COUNT(DISTINCT CAST(ts AS DATE))     AS days,
    SUM(is_fraud)                        AS total_fraud_txns,
    SUM(amt) FILTER (WHERE is_fraud = 1) AS total_fraud_amt
FROM sweep_base;

-- Adds the standard metric columns to a sweep table that has
-- alerts, fraud_alerts and fraud_amt_caught.
CREATE OR REPLACE MACRO sweep_metrics(sweep_table) AS TABLE
SELECT
    s.* EXCLUDE (alerts, fraud_alerts, fraud_amt_caught),
    s.alerts,
    ROUND(s.alerts / t.days, 2)                                      AS alerts_per_day,
    s.fraud_alerts,
    ROUND(100.0 * s.fraud_alerts / NULLIF(s.alerts, 0), 2)           AS precision_pct,
    ROUND((s.alerts - s.fraud_alerts) / NULLIF(s.fraud_alerts, 0), 2) AS fp_per_fraud,
    ROUND(100.0 * s.fraud_alerts / t.total_fraud_txns, 2)            AS txn_recall_pct,
    ROUND(s.fraud_amt_caught, 2)                                     AS fraud_amt_caught,
    ROUND(100.0 * s.fraud_amt_caught / t.total_fraud_amt, 2)         AS value_detection_pct,
    ROUND(s.fraud_amt_caught - s.alerts * getvariable('review_cost'), 2) AS net_benefit
FROM query_table(sweep_table) s
CROSS JOIN sweep_totals t;


-- R1: window length x minimum count. v1 = 60 min, 5.
CREATE OR REPLACE TABLE sweep_r1 AS
WITH grid AS (
    SELECT w AS window_min, n AS min_count
    FROM (VALUES (60), (120), (180)) ws(w) CROSS JOIN (VALUES (3), (4), (5), (6)) ns(n)
)
SELECT
    g.window_min, g.min_count,
    COUNT(*) FILTER (WHERE hit)                         AS alerts,
    COUNT(*) FILTER (WHERE hit AND b.is_fraud = 1)      AS fraud_alerts,
    COALESCE(SUM(b.amt) FILTER (WHERE hit AND b.is_fraud = 1), 0) AS fraud_amt_caught
FROM grid g
CROSS JOIN LATERAL (
    SELECT is_fraud, amt,
        CASE g.window_min WHEN 60 THEN txn_count_60m WHEN 120 THEN txn_count_120m ELSE txn_count_180m END
            >= g.min_count AS hit
    FROM sweep_base
) b
GROUP BY g.window_min, g.min_count;

-- R2: multiple of the previous-30 average x minimum amount. v1 = 5x, no floor.
CREATE OR REPLACE TABLE sweep_r2 AS
WITH grid AS (
    SELECT m AS multiple, a AS min_amt
    FROM (VALUES (3), (5), (8), (10)) ms(m) CROSS JOIN (VALUES (0), (100), (200), (300), (500)) amts(a)
)
SELECT
    g.multiple, g.min_amt,
    COUNT(b.amt)                                        AS alerts,
    COALESCE(SUM(b.is_fraud), 0)                        AS fraud_alerts,
    COALESCE(SUM(b.amt) FILTER (WHERE b.is_fraud = 1), 0) AS fraud_amt_caught
FROM grid g
LEFT JOIN sweep_base b
    ON b.prior_txn_count >= 1
   AND b.amt > g.multiple * b.avg_amt_prev30
   AND b.amt > g.min_amt
GROUP BY g.multiple, g.min_amt;

-- R3: amount threshold inside the 22:00-03:59 window. v1 = 500.
CREATE OR REPLACE TABLE sweep_r3 AS
WITH grid AS (SELECT a AS min_amt FROM (VALUES (200), (300), (400), (500), (600), (750)) amts(a))
SELECT
    g.min_amt,
    COUNT(b.amt)                                        AS alerts,
    COALESCE(SUM(b.is_fraud), 0)                        AS fraud_alerts,
    COALESCE(SUM(b.amt) FILTER (WHERE b.is_fraud = 1), 0) AS fraud_amt_caught
FROM grid g
LEFT JOIN sweep_base b
    ON (b.hour_of_day >= 22 OR b.hour_of_day < 4)
   AND b.amt > g.min_amt
GROUP BY g.min_amt;

-- R4: each category's threshold on its own. v1 = 500 / 500 / 500 / 300.
-- The categories do not overlap, so the rule's total is the sum of one row per category.
CREATE OR REPLACE TABLE sweep_r4 AS
WITH grid AS (
    SELECT c AS category, a AS min_amt
    FROM (VALUES ('shopping_net'), ('misc_net'), ('shopping_pos'), ('grocery_pos')) cs(c)
    CROSS JOIN (VALUES (200), (250), (300), (400), (500), (600), (750), (900)) amts(a)
)
SELECT
    g.category, g.min_amt,
    COUNT(b.amt)                                        AS alerts,
    COALESCE(SUM(b.is_fraud), 0)                        AS fraud_alerts,
    COALESCE(SUM(b.amt) FILTER (WHERE b.is_fraud = 1), 0) AS fraud_amt_caught
FROM grid g
LEFT JOIN sweep_base b
    ON b.category = g.category
   AND b.amt > g.min_amt
GROUP BY g.category, g.min_amt;

-- R5: distance threshold. v1 = 100 km.
CREATE OR REPLACE TABLE sweep_r5 AS
WITH grid AS (SELECT d AS min_km FROM (VALUES (25), (50), (100), (125), (150)) ds(d))
SELECT
    g.min_km,
    COUNT(b.amt)                                        AS alerts,
    COALESCE(SUM(b.is_fraud), 0)                        AS fraud_alerts,
    COALESCE(SUM(b.amt) FILTER (WHERE b.is_fraud = 1), 0) AS fraud_amt_caught
FROM grid g
LEFT JOIN sweep_base b
    ON b.distance_km > g.min_km
GROUP BY g.min_km;

-- R6: minimum prior transactions N x amount Y. v1 = 10, 300.
CREATE OR REPLACE TABLE sweep_r6 AS
WITH grid AS (
    SELECT n AS min_prior_txns, y AS min_amt
    FROM (VALUES (5), (10), (20)) ns(n) CROSS JOIN (VALUES (200), (300), (500), (750), (1000)) ys(y)
)
SELECT
    g.min_prior_txns, g.min_amt,
    COUNT(b.amt)                                        AS alerts,
    COALESCE(SUM(b.is_fraud), 0)                        AS fraud_alerts,
    COALESCE(SUM(b.amt) FILTER (WHERE b.is_fraud = 1), 0) AS fraud_amt_caught
FROM grid g
LEFT JOIN sweep_base b
    ON b.first_visit
   AND b.prior_txn_count >= g.min_prior_txns
   AND b.amt > g.min_amt
GROUP BY g.min_prior_txns, g.min_amt;

-- R7: window x multiple x spend floor x minimum active days. v1 = 24 h, 3x, no floor, 7 days.
-- The 48 h window is compared with 2 days of baseline so both read as "x times normal".
CREATE OR REPLACE TABLE sweep_r7 AS
WITH grid AS (
    SELECT w AS window_hours, m AS multiple, f AS min_spend, d AS min_active_days
    FROM (VALUES (24), (48)) ws(w)
    CROSS JOIN (VALUES (3), (4), (5)) ms(m)
    CROSS JOIN (VALUES (0), (300), (500), (1000)) fs(f)
    CROSS JOIN (VALUES (7), (14)) ds(d)
),
candidates AS (
    SELECT is_fraud, amt, prior_active_days, baseline_daily_avg, spend_24h, spend_48h
    FROM sweep_base
    WHERE prior_active_days >= 7
)
SELECT
    g.window_hours, g.multiple, g.min_spend, g.min_active_days,
    COUNT(b.amt)                                        AS alerts,
    COALESCE(SUM(b.is_fraud), 0)                        AS fraud_alerts,
    COALESCE(SUM(b.amt) FILTER (WHERE b.is_fraud = 1), 0) AS fraud_amt_caught
FROM grid g
LEFT JOIN candidates b
    ON b.prior_active_days >= g.min_active_days
   AND CASE WHEN g.window_hours = 24 THEN b.spend_24h ELSE b.spend_48h END
        > g.multiple * (g.window_hours / 24) * b.baseline_daily_avg
   AND CASE WHEN g.window_hours = 24 THEN b.spend_24h ELSE b.spend_48h END > g.min_spend
GROUP BY g.window_hours, g.multiple, g.min_spend, g.min_active_days;


-- Candidate rule definitions, written out from the features so that v1 and the
-- options considered stay reproducible after sql/10 moves to v2.
CREATE OR REPLACE TABLE candidate_flags AS
SELECT
    trans_num, is_fraud, amt,
    txn_count_60m >= 5                                                  AS v1_r1,
    prior_txn_count >= 1 AND amt > 5 * avg_amt_prev30                  AS v1_r2,
    (hour_of_day >= 22 OR hour_of_day < 4) AND amt > 500                AS v1_r3,
    (category IN ('shopping_net', 'misc_net', 'shopping_pos') AND amt > 500)
        OR (category = 'grocery_pos' AND amt > 300)                     AS v1_r4,
    distance_km > 100                                                   AS v1_r5,
    first_visit AND prior_txn_count >= 10 AND amt > 300                 AS v1_r6,
    prior_active_days >= 7 AND spend_24h > 3 * baseline_daily_avg       AS v1_r7,
    prior_txn_count >= 1 AND amt > 5 * avg_amt_prev30 AND amt > 500     AS tuned_r2,
    (hour_of_day >= 22 OR hour_of_day < 4) AND amt > 600                AS v2_r3,
    (category IN ('shopping_net', 'misc_net', 'shopping_pos') AND amt > 600)
        OR (category = 'grocery_pos' AND amt > 250)                     AS v2_r4,
    first_visit AND prior_txn_count >= 10 AND amt > 750                 AS v2_r6,
    prior_active_days >= 7 AND spend_48h > 5 * 2 * baseline_daily_avg   AS v2_r7
FROM sweep_base;

CREATE OR REPLACE TABLE candidate_sets(set_name, member) AS
VALUES
    ('1 v1 all (R1-R7)', 'v1_r1'), ('1 v1 all (R1-R7)', 'v1_r2'), ('1 v1 all (R1-R7)', 'v1_r3'),
    ('1 v1 all (R1-R7)', 'v1_r4'), ('1 v1 all (R1-R7)', 'v1_r5'), ('1 v1 all (R1-R7)', 'v1_r6'),
    ('1 v1 all (R1-R7)', 'v1_r7'),
    ('2 v1 without R5', 'v1_r1'), ('2 v1 without R5', 'v1_r2'), ('2 v1 without R5', 'v1_r3'),
    ('2 v1 without R5', 'v1_r4'), ('2 v1 without R5', 'v1_r6'), ('2 v1 without R5', 'v1_r7'),
    ('3 tuned before retiring R1 and R2', 'v1_r1'), ('3 tuned before retiring R1 and R2', 'tuned_r2'),
    ('3 tuned before retiring R1 and R2', 'v2_r3'), ('3 tuned before retiring R1 and R2', 'v2_r4'),
    ('3 tuned before retiring R1 and R2', 'v2_r6'), ('3 tuned before retiring R1 and R2', 'v2_r7'),
    ('4 v2 with R3 at 500', 'v1_r3'), ('4 v2 with R3 at 500', 'v2_r4'),
    ('4 v2 with R3 at 500', 'v2_r6'), ('4 v2 with R3 at 500', 'v2_r7'),
    ('5 v2 active (R3 R4 R6 R7)', 'v2_r3'), ('5 v2 active (R3 R4 R6 R7)', 'v2_r4'),
    ('5 v2 active (R3 R4 R6 R7)', 'v2_r6'), ('5 v2 active (R3 R4 R6 R7)', 'v2_r7');

CREATE OR REPLACE TABLE candidate_hits AS
SELECT trans_num, is_fraud, amt, member, hit
FROM candidate_flags
UNPIVOT (hit FOR member IN (COLUMNS(* EXCLUDE (trans_num, is_fraud, amt))));

CREATE OR REPLACE TABLE set_alerts AS
SELECT s.set_name, h.trans_num, ANY_VALUE(h.is_fraud) AS is_fraud, ANY_VALUE(h.amt) AS amt
FROM candidate_hits h
JOIN candidate_sets s USING (member)
WHERE h.hit
GROUP BY s.set_name, h.trans_num;

CREATE OR REPLACE TABLE sweep_sets AS
SELECT
    set_name,
    COUNT(*)                                            AS alerts,
    SUM(is_fraud)                                       AS fraud_alerts,
    COALESCE(SUM(amt) FILTER (WHERE is_fraud = 1), 0)   AS fraud_amt_caught
FROM set_alerts
GROUP BY set_name;

-- Leave-one-out inside set 3: what each member adds on top of all the others.
CREATE OR REPLACE TABLE sweep_set3_leave_one_out AS
WITH members AS (
    SELECT member FROM candidate_sets WHERE set_name = '3 tuned before retiring R1 and R2'
),
member_hits AS (
    SELECT h.trans_num, h.is_fraud, h.amt, h.member, h.hit
    FROM candidate_hits h JOIN members USING (member)
),
per_txn AS (
    SELECT trans_num, COUNT(*) FILTER (WHERE hit) AS members_fired
    FROM member_hits GROUP BY trans_num
)
SELECT
    m.member                                                       AS removed_member,
    COUNT(*) FILTER (WHERE m.hit AND p.members_fired = 1)          AS alerts,
    COUNT(*) FILTER (WHERE m.hit AND p.members_fired = 1 AND m.is_fraud = 1) AS fraud_alerts,
    COALESCE(SUM(m.amt) FILTER (WHERE m.hit AND p.members_fired = 1 AND m.is_fraud = 1), 0)
                                                                   AS fraud_amt_caught
FROM member_hits m
JOIN per_txn p USING (trans_num)
GROUP BY m.member;


-- name: candidate_set_comparison
SELECT * FROM sweep_metrics('sweep_sets') ORDER BY set_name;

-- name: set3_leave_one_out
-- Each row: the alerts and fraud that ONLY this member catches within set 3,
-- i.e. what removing it would save and lose.
SELECT * FROM sweep_metrics('sweep_set3_leave_one_out') ORDER BY removed_member;

-- name: r1_sweep
SELECT * FROM sweep_metrics('sweep_r1') ORDER BY window_min, min_count;

-- name: r2_sweep
SELECT * FROM sweep_metrics('sweep_r2') ORDER BY multiple, min_amt;

-- name: r3_sweep
SELECT * FROM sweep_metrics('sweep_r3') ORDER BY min_amt;

-- name: r4_sweep
SELECT * FROM sweep_metrics('sweep_r4') ORDER BY category, min_amt;

-- name: r5_sweep
SELECT * FROM sweep_metrics('sweep_r5') ORDER BY min_km;

-- name: r6_sweep
SELECT * FROM sweep_metrics('sweep_r6') ORDER BY min_prior_txns, min_amt;

-- name: r7_sweep
SELECT * FROM sweep_metrics('sweep_r7') ORDER BY window_hours, multiple, min_spend, min_active_days;
