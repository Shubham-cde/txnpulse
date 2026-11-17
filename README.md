# TxnPulse — Transaction-Monitoring Rules System

Status: work in progress (Phase 2, rule testing, done). The full write-up comes in Phase 4.

TxnPulse runs on simulated card data and covers the work of a bank's fraud rules team:
- write transaction-monitoring rules in SQL
- test them like UAT
- tune them on a training period
- validate them unchanged on a later period
- run them with production controls

## Rules (draft, untuned starting values)

All rules read the table `txn` and write one boolean column to `flags`
([sql/10_features_and_flags.sql](sql/10_features_and_flags.sql)). Every window ends at the
current transaction, and averages exclude it.

Figures are from the training period: 2019-01-01 to 2020-06-21, 1,296,675 transactions,
7,506 fraud transactions worth $3,988,088.61, 537 days. They come from
`outputs/train/rule_performance.csv`, `value_detection.csv` and `unique_catches.csv`.
Thresholds are starting hypotheses; Phase 3 tunes them.

| ID | Rule | Logic | Action | Alerts/day | Precision | Txn recall | Value detection | Unique fraud catches |
|---|---|---|---|---|---|---|---|---|
| R1 | Card velocity | 5 or more of the card's transactions in the last 60 minutes, including the current one | ALERT | 1.11 | 21.61% | 1.72% | 2.11% | 2 |
| R2 | Amount spike | Card has 1 or more prior transactions and amt > 5 x the average of its previous 30 | STEP_UP | 51.91 | 9.36% | 34.75% | 55.73% | 36 |
| R3 | Late-night high value | Hour 22:00-03:59 and amt > 500 | HOLD_CONFIRM | 10.60 | 53.88% | 40.87% | 69.47% | 1 |
| R4 | Risky category + amount | amt > 500 in shopping_net, misc_net, shopping_pos; amt > 300 in grocery_pos | ALERT | 22.77 | 37.59% | 61.24% | 88.97% | 183 |
| R5 | Distance anomaly | Cardholder-to-merchant distance > 100 km | ALERT | 563.97 | 0.58% | 23.27% | 23.60% | 179 |
| R6 | New merchant + high amount | First visit to the merchant, card has 10 or more prior transactions, amt > 300 | STEP_UP | 23.15 | 17.14% | 28.39% | 41.02% | 4 |
| R7 | 24-hour spend burst | Card has 7 or more prior active days and its 24-hour spend > 3 x its average daily spend over the previous 30 active days | HOLD_CONFIRM | 178.01 | 6.09% | 77.58% | 83.49% | 1,349 |
| R8 | Risk-list hit | Merchant on a versioned risk list built from training data only; evaluated on the test period only | BLOCK / HOLD by tier | [TBD] | [TBD] | [TBD] | [TBD] | [TBD] |
| | Any rule (R1-R7) | At least one rule fires; each transaction counted once | | 723.12 | 1.77% | 91.58% | 98.48% | |

Notes on the starting values:
- **R5:** precision is 0.58%, the same as the training fraud rate (0.579%). Distance carries
  no signal in this data; Phase 3 decides retirement on this evidence.
- **Workload:** R5 and R7 drive the combined volume of 723 alerts per day. Neither rule is
  usable at its starting threshold.
- **Unique fraud catches:** fraud transactions caught by that rule and no other.
- **Card detection:** across all 762 compromised cards, any rule detects 760 (99.74%).
  Median loss before the first alert is 0 fraud transactions and $0; P90 is 1 transaction
  and $128.85 (`card_detection.csv`, `loss_before_first_alert.csv`).

## Rule testing (UAT)

`tests/uat_cases.csv` holds 42 hand-written scenarios (212 transactions) covering:
- thresholds below, at and above the limit
- window edges and midnight wrap
- duplicate timestamps
- cards with no history

Each case runs `sql/10` unchanged on its own rows. The suite needs no Kaggle data.

Two defects were found and fixed: the R1 and R7 windows counted same-second transactions
that come after the current one. After the fix, all 42 cases pass. Details and known gaps
are in [reports/uat_report.md](reports/uat_report.md).

## Reproduce (so far)

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe src/profile_data.py
.venv\Scripts\python.exe src/run_rules.py --period train
.venv\Scripts\python.exe -m pytest tests
.venv\Scripts\python.exe src/run_uat.py
```

The Kaggle files `fraudTrain.csv` and `fraudTest.csv` go in `data/`.
