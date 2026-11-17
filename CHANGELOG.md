# Changelog

Versioning:
- **Rule version** (`major.minor`) tracks a rule's logic:
  - **Minor:** a logic fix that does not change the business definition or thresholds.
  - **Major:** a threshold or definition change.
- **Rule set version** (`v1.1`, `v2`, `v2.1`, matching git tags `rules-*`) tracks the set
  as deployed. A status change (active, shadow, retired) changes the rule set version, not
  the rule version. For example, R1, R2 and R5 kept their versions when they were retired
  in set v2.

## 2026-11-17: rule set v2.1 (R6 to shadow)

The first change through the pull request process. The PR description is kept with the
project notes.

### Rules
- **R6:** status active to shadow. Logic unchanged at version 2.0. All other rules are
  unchanged.
- **Reason:** PVT on v2 showed R6 set the first response for 0 of 215 detected cards and
  lost 0 fraud if removed. That meets the pre-agreed shadow rule. Its train figures were
  partly a warm-up artifact (9.54% recall in the last 3 months of train, against 18.40%
  overall).

### Impact
| | v2 | v2.1 |
|---|---|---|
| Train: alerts per day | 37.80 | 37.36 |
| Train: cases per day | 17.21 | 16.79 |
| Train: precision | 31.40% | 31.77% |
| Train: recall | 84.92% | 84.92% |
| Train: value detection | 98.04% | 98.04% |
| Test (impact estimate, not out-of-sample validation): alerts per day | 41.20 | 41.02 |
| Test: cases per day | 18.78 | 18.63 |
| Test: precision | 22.21% | 22.30% |
| Test: recall | 82.75% | 82.75% |
| Test: value detection | 97.41% | 97.41% |

- **Customer-facing STEP_UP actions go to 0.** 699 train alerts (38 on test) that R4 also
  raises become post-event ALERT reviews. That includes 52 train frauds ($47,138.14) and
  1 test fraud ($850.57).
- **Rollback was tested:** with R6 set back to active, the active set returned to 20,300
  train alerts and 7,992 test alerts.

### Approvals
- Rule set v2.1 checker: self-review against the PR checklist, with required CI checks;
  solo project.
- Rule sets v1 and v2: self-reviewed (before the review process).

### Reports
- The v2 PVT evidence is kept fixed: `reports/pvt_evidence/pvt_rule_comparison_v2.csv`,
  `reports/figures/pvt_*_v2.png` and `reports/figures/tuning_monthly_alerts_train_v2.png`.
- The unsuffixed charts are redrawn by `run_all.py` for the current rule set. Their titles
  no longer name a version.

## 2026-11-17: documentation and governance (rule set unchanged, still v2)

### Governance
- `run_all.py` reproduces every output, chart and the UAT report table from the raw CSVs in
  one command (about 25 seconds).
- `.github/workflows/uat.yml` runs the test suite on every push and pull request. It needs
  no Kaggle data.
- `.github/pull_request_template.md` covers: rule, version change, business intent,
  backtest before and after, PVT, UAT evidence, workload impact, rollback plan, and
  maker/checker.
- The rule register now carries owner, date, UAT IDs and train and test performance for
  every rule.
- The README tells the full story with real results and limitations.
- Versioning clarified: a status change moves the rule set version, not the rule version.

### Analysis (no rule change)
- `r6_burn_in_check` (`sql/40`, train only) and `profile_first_visit_by_month` (`sql/35`)
  show R6's train performance was partly a warm-up artifact.
  - First visits fall from 94.16% of transactions in January 2019 to 7.17% in December
    2020.
  - R6's recall is 18.40% over all of train, but 9.54% over the last 3 months of train.
  - Lesson: history-dependent rules need a burn-in period excluded from tuning.
- **Holdout rule:** any version changed because of PVT findings reports its test figures as
  an impact estimate, not out-of-sample validation.
- **First change request drafted:** R6 to shadow (rule set v2 to v2.1). Not applied.

## 2026-11-17: post-deployment validation of rule set v2 (`rules-v2`)

No rule or threshold changed. Results are in `reports/pvt_report.md`.
- **Active set on test:** 41.20 alerts and 18.78 cases per day, precision 22.21% (23.35%
  expected from the lower base rate), recall 82.75%, value detection 97.41%, 215 of 218
  cards detected.
- **R3, R4 and R7 pass.**
- **R6:** recall fell from 18.40% to 7.04% as cards built up history, and it set the first
  response for 0 cards. Shadow recommended at the next review.
- **R8 (shadow):** 1.12% precision with no unique catches. Not promoted.
- **Added** `sql/35_period_profile.sql` (both periods), `sql/50_pvt_test.sql` (test only)
  and `src/compare_pvt.py`. The `amount_band` macro moved to `sql/05_macros.sql`.

### Documentation
- R6's justification is now based only on the 28 cards (3.71%) where it sets a stronger
  first response. The 17.09% "fired on the first alert" figure is presented as co-firing.

## 2026-11-17: rule set v2 (approved and frozen)

All changes are based on train only. Evidence is in `reports/tuning_report.md`.

Frozen versions: R1 1.1 (retired), R2 1.0 (retired), R3 2.0, R4 2.0, R5 1.0 (retired),
R6 2.0, R7 2.0, R8 1.0 (shadow, risk list v1). The previous set (v1.0/v1.1) can be
reproduced from git tag `rules-v1.1`.

Approved decisions:
- **R3 at $600:** $500 would add 1.71 alerts per day for +0.36 points of recall, about 2.9%
  precision on the extra alerts.
- **R6 active:** under the approved test it loses 0 fraud if removed, but it sets a
  stronger first response (STEP_UP instead of ALERT) for 28 of 755 detected cards (3.71%),
  above the 1% bar. Its 17.09% "fired on the first alert" figure is co-firing with other
  rules and is not counted as its own contribution.
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
