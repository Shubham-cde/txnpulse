# Changelog

Rule versions follow `major.minor`:
- **Minor:** a logic fix that does not change the business definition or thresholds.
- **Major:** a threshold or definition change, or a status change such as retirement.

## 2026-11-17: rule set v2 (approved and frozen)

All changes are based on train only. Evidence is in `reports/tuning_report.md`.

Frozen versions: R1 1.1 (retired), R2 1.0 (retired), R3 2.0, R4 2.0, R5 1.0 (retired),
R6 2.0, R7 2.0, R8 1.0 (shadow, risk list v1). The previous set (v1.0/v1.1) can be
reproduced from git tag `rules-v1.1`.

Approved decisions:
- **R3 at $600:** $500 would add 1.71 alerts per day for +0.36 points of recall, about 2.9%
  precision on the extra alerts.
- **R6 active:** under the approved test it loses 0 fraud if removed, but it is on the
  first alert for 17.09% of detected cards (3.71% where it sets the action), above the 1%
  bar.
- **Alert budget:** 50 per day, assumed (one analyst, about 9 minutes per alert). December
  2019 (74.32 alerts, 32.42 cases per day) is a peak-staffing finding, not a threshold
  change.
- **R8 in shadow.**

### Rules
- **R3 v2.0:** amount threshold 500 to 600.
- **R4 v2.0:** per-category thresholds; grocery_pos 300 to 250, and shopping_net, misc_net
  and shopping_pos 500 to 600.
- **R6 v2.0:** amount threshold 300 to 750 (N stays 10).
- **R7 v2.0:** 24 h spend above 3 times the daily baseline changed to 48 h spend above
  5 times two days of baseline. Column renamed `r7_spend_burst_24h` to `r7_spend_burst`;
  new feature `spend_48h`.
- **R1 (v1.1), R2 (v1.0), R5 (v1.0) retired.** They are still computed for monitoring and
  no longer alert.
- **R8 v1.0 added in shadow,** with merchant risk list v1
  (`rules/risk_lists/merchant_risk_v1.csv`, built from train by `src/build_risk_list.py`).
  It is scored on the test period only (`sql/15_r8_risk_list.sql`).
- **Impact on train:** the active set goes from 723.12 to 37.80 alerts per day, precision
  from 1.77% to 31.40%, transaction recall from 91.58% to 84.92%, and value detection from
  98.48% to 98.04%.

### Pipeline
- `sql/20`: rule catalogue with version, status and action. The combined metrics now count
  active rules (`any_active`) and active plus shadow (`any_active_or_shadow`).
- `sql/30`: case grouping (24 h per card), first-alert view (including which rule set the
  first action), action mix, monthly alerts and cases;
  unique catches are now measured against the other active rules (leave-one-out).
- `sql/40`: sweeps for every rule, a candidate rule-set comparison, and leave-one-out for
  the pre-retirement set.
- `src/make_figures.py`: tuning charts in `reports/figures/`.

### Testing
- UAT now has 50 cases (220 rows). The v2 thresholds failed 10 boundary cases built on v1,
  as expected (`reports/uat_evidence/pytest_v2_before_case_update.txt`). Those cases were
  rewritten for v2, and R8 cases were added. 50 of 50 pass.

## 2026-11-17: rule set v1

### Rules
- **R1 v1.1 and R7 v1.1: window end fix (DEF-01, DEF-02).**
  - The 60-minute count (R1) and 24-hour spend (R7) included transactions at the same second
    that sort after the current one. They now end at the current row: same-second
    transactions are taken in (ts, trans_num) order, which is how the streaming engine will
    process them.
  - Found by UAT-R1-06 and UAT-R7-09.
  - Impact on train: `txn_count_60m` and `spend_24h` changed on 20 rows (the earlier row of
    each same-card, same-second pair). 0 flags flipped. Every metric in
    `rule_performance.csv` and `value_detection.csv` is identical before and after.
  - Thresholds unchanged.
- **R1 to R7 v1.0: initial versions** with the starting values from the rule catalogue
  (R4, R5 thresholds from the Phase 0 EDA on train).

### Testing
- Added the UAT suite: `tests/uat_cases.csv` (42 cases, 212 rows), `tests/test_rules.py`,
  `src/run_uat.py`, `reports/uat_report.md`. Evidence of the pre-fix failures is in
  `reports/uat_evidence/`.

### Pipeline
- Added the loader, DQ checks and train-only EDA (`sql/00`, `sql/01`, `sql/02`), shared
  macros (`sql/05`), rule features and flags (`sql/10`), performance and metrics
  (`sql/20`, `sql/30`) and train-only sweeps (`sql/40`).
