# Power BI build guide: TxnPulse dashboard

This guide builds a four-page Power BI dashboard from the CSV extracts, step by step. It
assumes you have never used Power BI Desktop. Every measure is ready to paste, and section
7 lists the numbers each page must show, so you can check your build.

- **Rule set:** v2.1 (active R3, R4, R7; shadow R6, R8; retired R1, R2, R5)
- **ML model:** v1
- **Periods:**
  - train: 2019-01-01 to 2020-06-21, 537 days
  - test: 2020-06-21 to 2020-12-31, 194 days

## 1. Before you start
1. Install Power BI Desktop (free, from the Microsoft Store).
2. Build the extracts. Either run `.venv\Scripts\python.exe run_all.py` (everything, about
   2 minutes), or run `.venv\Scripts\python.exe dashboards/build_extracts.py` after the ML
   step has run once.
3. The files are in `dashboards/extracts/`. They are not committed; they are rebuilt from the
   raw CSVs.

| File | Rows | One row per | Key |
|---|---|---|---|
| fact_alerts.csv | 28,021 | alert from the v2.1 active set (both periods) | alert_id; joins on date_key |
| fact_daily_rule.csv | 3,043 | date, period and rule (active and shadow rules only) | date_key + rule_id |
| agg_hour_category.csv | 504 | period, hour and category, over ALL transactions | period + hour + category |
| dim_date.csv | 731 | date and period | date_key |
| dim_rule.csv | 8 | rule R1 to R8 | rule_id |
| dim_period.csv | 2 | period (train, test) | period |
| expected_values.csv | 60 | check value (not loaded into Power BI) | |

**Why `date_key` and not `date`:** 2020-06-21 belongs to both periods (the split happens
at 12:14 that day). `date_key` is `train_2020-06-21` or `test_2020-06-21`, so each period
keeps its own day.

**About the model score on train:** model v1 was fitted on the train alerts, so train scores
are in-sample (`score_in_sample` = TRUE). Use the test period on page 4. Train precision@K
looks better than it would on new data.

## 2. Import the CSVs and set data types
For each of the six CSV files (not `expected_values.csv`):
1. **Home > Get data > Text/CSV**, then choose the file.
2. In the preview window click **Transform Data**. This opens Power Query.
3. Check each column's type. The icon left of the column name shows the type; click the
   icon to change it. Use the table below.
4. **Home > Close & Apply.**

After the first file, use **Home > New source > Text/CSV** inside Power Query for the
others, then Close & Apply once.

| Table | Column | Type |
|---|---|---|
| fact_alerts | alert_id, date_key, period, card, category, rules_fired, strongest_action, reason_codes, case_id | Text |
| fact_alerts | alert_time | Date/Time |
| fact_alerts | alert_date | Date |
| fact_alerts | hour, active_rules_count, fired_r3, fired_r4, fired_r7, daily_rank, is_case_opening, is_fraud | Whole number |
| fact_alerts | amount, model_score | Decimal number |
| fact_alerts | score_in_sample | True/False |
| fact_daily_rule | date_key, period, rule_id | Text |
| fact_daily_rule | alerts, cases, fraud_alerts, day_transactions | Whole number |
| fact_daily_rule | fraud_value_caught | Decimal number |
| agg_hour_category | period, category | Text |
| agg_hour_category | hour, transactions, fraud_transactions | Whole number |
| agg_hour_category | fraud_value | Decimal number |
| dim_date | date_key, month, weekday, period | Text |
| dim_date | date | Date |
| dim_date | weekday_number, is_december, day_transactions, day_fraud_transactions | Whole number |
| dim_date | day_fraud_value | Decimal number |
| dim_rule | all columns | Text |
| dim_period | period, period_label | Text |
| dim_period | period_order | Whole number |

If dates load as text or in the wrong order, check **File > Options and settings > Options
> Regional settings**. The files use ISO dates (YYYY-MM-DD), which Power BI reads in any
locale when the column type is Date.

Two sort settings, in **Data view**:
- select `dim_period[period_label]`, then **Column tools > Sort by column > period_order**
- select `dim_date[weekday]`, then sort by `weekday_number`

## 3. Relationships
Open **Model view** (the third icon on the left). Power BI may have guessed some
relationships: delete any it created, then drag each one below from the "one" side to the
"many" side. Every relationship is **one-to-many** with **single** cross-filter direction.

| From (one) | To (many) |
|---|---|
| dim_period[period] | dim_date[period] |
| dim_period[period] | agg_hour_category[period] |
| dim_date[date_key] | fact_alerts[date_key] |
| dim_date[date_key] | fact_daily_rule[date_key] |
| dim_rule[rule_id] | fact_daily_rule[rule_id] |

Do **not** relate `fact_alerts[period]` or `fact_daily_rule[period]` to anything. Period
filtering flows dim_period to dim_date to the facts; a second path would make the model
ambiguous.

**dim_rule does not filter fact_alerts.** One alert can be raised by several rules, which
would need a many-to-many relationship. To filter the alert queue by rule, use the
`fired_r3`, `fired_r4` and `fired_r7` columns, or `rules_fired`.

## 4. Measures (paste-ready DAX)
Create a home for the measures: **Home > Enter data**, name the table `Measures`, click
Load. Then for each measure: select the `Measures` table, **Modeling > New measure**, paste
the whole line, press Enter. Set the format in **Measure tools** (% for precision, recall
and value detection; 2 decimals for per-day figures).

### Active set (from fact_alerts)
```DAX
Alerts = COUNTROWS ( fact_alerts )
Fraud alerts = CALCULATE ( [Alerts], fact_alerts[is_fraud] = 1 )
Cases = CALCULATE ( [Alerts], fact_alerts[is_case_opening] = 1 )
Days = COUNTROWS ( dim_date )
Alerts per day = DIVIDE ( [Alerts], [Days] )
Cases per day = DIVIDE ( [Cases], [Days] )
Precision = DIVIDE ( [Fraud alerts], [Alerts] )
FP ratio = DIVIDE ( [Alerts] - [Fraud alerts], [Fraud alerts] )
Fraud transactions = SUM ( dim_date[day_fraud_transactions] )
Fraud value = SUM ( dim_date[day_fraud_value] )
Fraud value caught = CALCULATE ( SUM ( fact_alerts[amount] ), fact_alerts[is_fraud] = 1 )
Recall = DIVIDE ( [Fraud alerts], [Fraud transactions] )
Value detection = DIVIDE ( [Fraud value caught], [Fraud value] )
Budget = 50
```
How these work:
- **Cases** count only the opening alert of each case, so a case is counted once, on the
  day it opened (the same rule as `sql/30`).
- **Days** counts dim_date rows, so days with no alerts still count.
- **Recall and value detection** use the day totals in dim_date (all transactions, alerted
  or not). They are correct for period, month and date filters. They do not respond to a
  category filter, because dim_date has no category; use page 3 for categories.

### Daily queue: precision@K and value@K
First create the queue-size parameter: **Modeling > New parameter > Numeric range**, name
`Queue size`, minimum 5, maximum 50, increment 5, default 10, and tick **Add slicer to this
page**. Power BI creates a table `Queue size` and a measure `[Queue size Value]`.
```DAX
Alerts in top K = VAR k = [Queue size Value] RETURN CALCULATE ( [Alerts], fact_alerts[daily_rank] <= k )
Fraud in top K = VAR k = [Queue size Value] RETURN CALCULATE ( [Fraud alerts], fact_alerts[daily_rank] <= k )
Precision@K = DIVIDE ( [Fraud in top K], [Alerts in top K] )
Value@K (share of fraud value in the alert queue) = VAR k = [Queue size Value] RETURN DIVIDE ( CALCULATE ( [Fraud value caught], fact_alerts[daily_rank] <= k ), [Fraud value caught] )
Value@K (share of all fraud value) = VAR k = [Queue size Value] RETURN DIVIDE ( CALCULATE ( [Fraud value caught], fact_alerts[daily_rank] <= k ), [Fraud value] )
In queue = IF ( MAX ( fact_alerts[daily_rank] ) <= [Queue size Value], 1, 0 )
```
`daily_rank` is the model v1 rank within each day (1 = review first), so "top K" means the
first K alerts of every day in the filter.

### Per rule (from fact_daily_rule)
```DAX
Rule alerts = SUM ( fact_daily_rule[alerts] )
Rule cases = SUM ( fact_daily_rule[cases] )
Rule fraud alerts = SUM ( fact_daily_rule[fraud_alerts] )
Rule fraud value caught = SUM ( fact_daily_rule[fraud_value_caught] )
Rule alerts per day = DIVIDE ( [Rule alerts], [Days] )
Rule cases per day = DIVIDE ( [Rule cases], [Days] )
Rule precision = DIVIDE ( [Rule fraud alerts], [Rule alerts] )
Rule FP ratio = DIVIDE ( [Rule alerts] - [Rule fraud alerts], [Rule fraud alerts] )
Rule recall = DIVIDE ( [Rule fraud alerts], [Fraud transactions] )
Rule value detection = DIVIDE ( [Rule fraud value caught], [Fraud value] )
```

### Hour by category (from agg_hour_category)
```DAX
HC transactions = SUM ( agg_hour_category[transactions] )
HC fraud transactions = SUM ( agg_hour_category[fraud_transactions] )
HC fraud rate = DIVIDE ( [HC fraud transactions], [HC transactions] )
HC fraud value = SUM ( agg_hour_category[fraud_value] )
```

## 5. Slicers shared by all pages
Build these on page 1, then copy them to the other pages: select the slicer, Ctrl+C, go to
the page, Ctrl+V, and choose **Sync** when asked.

| Slicer | Field | Setting | Why |
|---|---|---|---|
| Period | dim_period[period_label] | Single select on; default the test period | Per-day measures assume one period. With both selected, 2020-06-21 counts as two days. |
| Month | dim_date[month] | Dropdown, multi-select allowed | Pick months inside the selected period |
| Rule | dim_rule[rule_id] | Multi-select | Filters the per-rule visuals (fact_daily_rule) only |

**Period slicer, setting single select:** select the slicer, then **Format > Slicer
settings > Selection > Single select**.

**Month slicer on page 3:** the heatmap table has no month column. To stop the month slicer
affecting it, select the month slicer, **Format > Edit interactions**, and click the "None"
icon on the heatmap.

## 6. Pages and visuals

### Page 1: Rule scorecard
| Visual | Type | Fields | Filters | What it should show |
|---|---|---|---|---|
| Alerts per day | Card | [Alerts per day] | none | Daily workload of the active set for the selected period |
| Cases per day | Card | [Cases per day] | none | Daily cases (alerts on one card within 24 h count once) |
| Precision | Card | [Precision] | none | Share of alerts that are fraud |
| Recall | Card | [Recall] | none | Share of fraud transactions the active set alerted on |
| Value detection | Card | [Value detection] | none | Share of fraud value the active set alerted on |
| Rule table | Table | dim_rule[rule_id], [rule_name], [status], [action], [logic_version], [Rule alerts per day], [Rule cases per day], [Rule precision], [Rule FP ratio], [Rule recall], [Rule value detection] | Visual filter: dim_rule[status] is active or shadow | One row per live or shadow rule; shadow rules are measured but do not alert |
| Budget gauge (optional) | Gauge | Value [Alerts per day], Maximum [Budget] | none | How close the daily workload is to the 50 budget |

Format the precision, recall and value detection cards as percentages with 2 decimals.

### Page 2: Monthly trend against the budget
| Visual | Type | Fields | Filters | What it should show |
|---|---|---|---|---|
| Alerts and cases per day | Line chart | X-axis dim_date[month]; Y-axis [Alerts per day], [Cases per day], [Budget] | none | Monthly workload against the 50-per-day budget. December peaks above the budget in alerts but not in cases. |
| Monthly table | Table | dim_date[month], [Alerts per day], [Cases per day], [Precision], [Recall], [Value detection] | none | The same numbers, with quality next to volume |

**The Budget line:** in the line chart **Format > Lines**, select the Budget series and
make it dashed and grey, so it reads as a reference line and not a data series.

For the whole timeline, select both periods. June 2020 then combines train (21 days) and
test (10 days) correctly, because dim_date holds 31 June rows across the two periods.

### Page 3: Hour by category heatmap
| Visual | Type | Fields | Filters | What it should show |
|---|---|---|---|---|
| Fraud rate heatmap | Matrix | Rows agg_hour_category[hour]; Columns agg_hour_category[category]; Values [HC fraud rate] | Month slicer interaction set to None | Where fraud concentrates: late-night hours in grocery_pos, shopping_net and misc_net |
| Volume heatmap | Matrix | Same rows and columns; Values [HC transactions] | same | Where volume sits, so a high rate on tiny volume is not over-read |

**Turning the matrix into a heatmap:** select the matrix, then **Format > Cell elements**.
Turn on **Background color**, then use **fx > Format style: Gradient** from white (lowest)
to a dark blue (highest). Set the values to percentages with 1 decimal.

### Page 4: Daily alert queue
| Visual | Type | Fields | Filters | What it should show |
|---|---|---|---|---|
| Date | Slicer | dim_date[date] | Single select; pick a test date | One day's queue |
| Queue size | Slicer | Queue size parameter | Default 10 | How many alerts the analyst reviews today |
| Precision@K | Card | [Precision@K] | none | Fraud share in the top K. Without a date selected it is the whole period. |
| Value@K | Card | [Value@K (share of fraud value in the alert queue)] | none | Fraud value in the top K as a share of fraud value in the queue |
| Queue | Table | fact_alerts[daily_rank], [alert_time], [card], [category], [amount], [rules_fired], [strongest_action], [model_score], [reason_codes], [is_fraud] | Optional visual filter: [In queue] is 1 | The day's alerts in model order, with the reasons for each score |

**Table settings:**
- **Sort:** click the daily_rank header until it sorts ascending, so rank 1 is on top.
- **model_score:** **Format > Cell elements > Data bars**.
- **Rule filter:** use **Add data to filter > fired_r3 / fired_r4 / fired_r7** in the
  Filters pane. The Rule slicer does not reach this table (section 3).

**Operating model reminder (put it in a text box on this page):** HOLD_CONFIRM alerts are
always worked, regardless of rank. The model only orders the queue and never removes an
alert.

## 7. Expected values: check your build
All values come from `dashboards/extracts/expected_values.csv` and agree with the project
reports. Select one period at a time and no month filter.

### Page 1 cards (active set)
| Card | Train | Test |
|---|---|---|
| Alerts per day | 37.36 | 41.02 |
| Cases per day | 16.79 | 18.63 |
| Precision | 31.77% | 22.30% |
| FP ratio | 2.15 | 3.48 |
| Recall | 84.92% | 82.75% |
| Value detection | 98.04% | 97.41% |
| Alerts (total) | 20,063 | 7,958 |
| Cases (total) | 9,015 | 3,614 |
| Days | 537 | 194 |

### Page 1 rule table
| Rule | Status | Alerts/day (train, test) | Cases/day (train, test) | Precision (train, test) | FP ratio (train, test) | Recall (train, test) | Value detection (train, test) |
|---|---|---|---|---|---|---|---|
| R3 | active | 8.78, 8.21 | 5.33, 5.46 | 63.37%, 53.77% | 0.58, 0.86 | 39.82%, 39.91% | 68.38%, 68.95% |
| R4 | active | 20.76, 20.49 | 13.34, 14.49 | 46.70%, 36.83% | 1.14, 1.72 | 69.37%, 68.25% | 93.31%, 93.13% |
| R6 | shadow | 6.09, 2.10 | 4.84, 1.87 | 42.21%, 37.10% | 1.37, 1.70 | 18.40%, 7.04% | 32.37%, 12.70% |
| R7 | active | 23.60, 26.55 | 6.67, 7.07 | 33.01%, 23.18% | 2.03, 3.31 | 55.74%, 55.66% | 63.91%, 64.35% |
| R8 | shadow | test only: 31.66 | 30.06 | 1.12% | 88.01 | 3.22% | 5.97% |

### Page 2 peaks
| Month | Alerts per day | Cases per day | Precision |
|---|---|---|---|
| 2019-12 (train) | 73.61 | 31.77 | 21.78% |
| 2020-12 (test) | 64.94 | 27.23 | 10.43% |

### Page 3 hottest cells (fraud rate)
| Period | Hour | Category | Fraud rate | Transactions |
|---|---|---|---|---|
| Train | 22 | grocery_pos | 44.37% | 302 |
| Train | 23 | grocery_pos | 43.24% | 340 |
| Test | 22 | grocery_pos | 31.06% | 132 |
| Test | 23 | grocery_pos | 21.67% | 120 |

Total transactions with no filter: 1,296,675 for train and 555,719 for test.

### Page 4
- **Precision@K, test period, no date selected:**
  - K = 10: 65.57%
  - K = 20: 44.15%
  - K = 30: 33.61%
- **Precision@K, train (in-sample):** 76.21%, 57.48%, 45.43% at K = 10, 20, 30.
- **Test, date 2020-12-21:** 83 alerts. The first three rows (ranks 1 to 3) are card
  XXXX5522, grocery_pos, $358.24, $338.60 and $349.96, all raised by R4 as ALERT, model
  scores 0.9997, 0.9997 and 0.9993, all fraud. R4 alone would put them behind every
  HOLD_CONFIRM; the model puts them first.

## 8. Troubleshooting
| Symptom | Likely cause | Fix |
|---|---|---|
| Per-day figures slightly low with both periods selected | 2020-06-21 counted twice in Days | Use single select on the Period slicer |
| Recall or Value detection blank | dim_date not related to the fact table | Check the dim_date[date_key] to fact relationships |
| Rule table shows the same numbers on every row | dim_rule to fact_daily_rule relationship missing | Create it in Model view |
| Precision@K blank | Queue size parameter not created or renamed | Recreate it with the exact name `Queue size` |
| Heatmap changes with the month slicer | Interaction not turned off | Format > Edit interactions > None on the matrix |
| Dates sorted as text | Column type is Text | Set dim_date[date] to Date in Power Query |
