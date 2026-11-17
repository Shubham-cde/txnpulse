# TxnPulse — Transaction-Monitoring Rules System

Status: work in progress. Phase 3 is done: rules tuned on train, frozen as rule set v2 (git
tag `rules-v2`) and validated unchanged on the later test period. The full write-up comes in
Phase 4.

TxnPulse runs on simulated card data and covers the work of a bank's fraud rules team:
- write transaction-monitoring rules in SQL
- test them like UAT
- tune them on a training period
- validate them unchanged on a later period
- run them with production controls

## Rules (set v2)

All rules read the table `txn` and write one boolean column to `flags`
([sql/10_features_and_flags.sql](sql/10_features_and_flags.sql);
R8 in [sql/15_r8_risk_list.sql](sql/15_r8_risk_list.sql)). Every window ends at the current
transaction, and averages exclude it.

| Period | Dates | Transactions | Fraud |
|---|---|---|---|
| Train | 2019-01-01 to 2020-06-21 (537 days) | 1,296,675 | 7,506 (0.579%) |
| Test | 2020-06-21 to 2020-12-31 (194 days) | 555,719 | 2,145 (0.386%) |

| ID | Version | Status | Logic | Action | Alerts/day (train, test) | Precision (train, test) | Txn recall (train, test) |
|---|---|---|---|---|---|---|---|
| R1 | 1.1 | Retired | 5 or more transactions on the card in 60 minutes | ALERT | 1.11, 1.95 | 21.61%, 7.41% | 1.72%, 1.31% |
| R2 | 1.0 | Retired | amt > 5 x average of the previous 30 transactions | STEP_UP | 51.91, 58.11 | 9.36%, 6.74% | 34.75%, 35.43% |
| R3 | 2.0 | Active | Hour 22:00-03:59 and amt > 600 | HOLD_CONFIRM | 8.78, 8.21 | 63.37%, 53.77% | 39.82%, 39.91% |
| R4 | 2.0 | Active | amt > 600 in shopping_net, misc_net, shopping_pos; amt > 250 in grocery_pos | ALERT | 20.76, 20.49 | 46.70%, 36.83% | 69.37%, 68.25% |
| R5 | 1.0 | Retired | Cardholder-to-merchant distance > 100 km | ALERT | 563.97, 669.22 | 0.58%, 0.38% | 23.27%, 23.08% |
| R6 | 2.0 | Active | First visit to the merchant, 10 or more prior transactions, amt > 750 | STEP_UP | 6.09, 2.10 | 42.21%, 37.10% | 18.40%, 7.04% |
| R7 | 2.0 | Active | 7 or more prior active days and 48-hour spend > 5 x two days of average daily spend | HOLD_CONFIRM | 23.60, 26.55 | 33.01%, 23.18% | 55.74%, 55.66% |
| R8 | 1.0 | Shadow | Merchant on risk list v1, built from train only; scored on test only | BLOCK / HOLD_CONFIRM by tier | -, 31.66 | -, 1.12% | -, 3.22% |
| | | | **Active set (R3, R4, R6, R7)**, each transaction counted once | | 37.80, 41.20 | 31.40%, 22.21% | 84.92%, 82.75% |

Active set, train then test:
- **Workload:** 17.21 and 18.78 cases per day, under the 50-per-day budget. Alerts on the
  same card within 24 hours count as one case.
- **Value detection:** 98.04% and 97.41%.
- **Cards detected:** 755 of 762 and 215 of 218.
- **Loss before the first alert (90th percentile per card):** 1 transaction / $22.21 and
  2 transactions / $34.42.

Retired rules are still computed for monitoring and do not alert.

## Tuning and validation

- **Tuning, train only** ([reports/tuning_report.md](reports/tuning_report.md)):
  - Every rule was swept over a grid of thresholds.
  - Rule sets were compared against an alert budget of 50 per day, an assumption (one
    analyst, about 9 minutes per alert).
  - R1, R2 and R5 were retired on leave-one-out evidence.
  - The v1 set raised 723 alerts per day at 1.77% precision; v2 raises 37.80 at 31.40%, for
    6.7 points less transaction recall.
- **Validation, frozen set on test** ([reports/pvt_report.md](reports/pvt_report.md)):
  - **Precision fell as the lower fraud rate predicts:** 23.35% expected and 22.21% actual
    for the active set.
  - **Recall and value detection held.**
  - **R6 decayed** as cards built up merchant history (first visits fell from 36.95% to
    9.04% of transactions), so it is recommended for shadow.
  - **R8 is not promoted.**

## Rule testing (UAT)

`tests/uat_cases.csv` holds 50 hand-written scenarios (220 transactions) covering:
- thresholds below, at and above the limit
- window edges and midnight wrap
- duplicate timestamps
- cards with no history
- risk-list matches

Each case runs the rule SQL unchanged on its own rows. The suite needs no Kaggle data.

Defects found and fixed:
- **DEF-01 and DEF-02:** the R1 and R7 windows counted same-second transactions that come
  after the current one.
- **The suite caught every v1 to v2 threshold change.**

All 50 cases pass. Details and known gaps are in [reports/uat_report.md](reports/uat_report.md).

## Limitations

- **Simulated data.** Fraud sits in narrow category, hour and amount bands, and its shape
  is the same in both periods. Precision here is higher than real card data would give.
- **Assumption-based figures:** the alert budget and the $5 review cost in net benefit are
  assumptions, not measured.
- **No upper amount caps** were used, even though train has no fraud above $1,500; that is a
  simulator artifact.

## Reproduce (so far)

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe src/profile_data.py
.venv\Scripts\python.exe src/build_risk_list.py
.venv\Scripts\python.exe src/run_rules.py --period train
.venv\Scripts\python.exe src/run_rules.py --period test
.venv\Scripts\python.exe src/compare_pvt.py
.venv\Scripts\python.exe src/make_figures.py
.venv\Scripts\python.exe -m pytest tests
.venv\Scripts\python.exe src/run_uat.py
```

The Kaggle files `fraudTrain.csv` and `fraudTest.csv` go in `data/`.
