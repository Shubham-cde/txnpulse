# Data dictionary

Source: Kaggle "Credit Card Transactions Fraud Detection" (kartik2112), generated with the
Sparkov simulator. Two files: `fraudTrain.csv` (used for analysis and tuning) and
`fraudTest.csv` (used only for post-deployment validation).

Both files are loaded by `sql/00_load.sql`. The loaded table keeps 16 columns. `src/db.py`
adds `is_scored` when it builds `txn`.

## Loaded columns

| Field | Raw name | Type | Meaning | Used in rules | Sensitive |
|---|---|---|---|---|---|
| trans_num | trans_num | VARCHAR | Unique transaction ID | N (row key) | N |
| ts | trans_date_trans_time | TIMESTAMP | Transaction date and time. Source of truth for all time logic | Y (R1, R3, R7) | N |
| card_id | cc_num | VARCHAR | Card number. Read as text because it is an identifier | Y (R1, R2, R6, R7) | Y |
| merchant | merchant | VARCHAR | Merchant name | Y (R6, R8) | N |
| category | category | VARCHAR | Merchant category, 14 values | Y (R4) | N |
| amt | amt | DOUBLE | Transaction amount in USD | Y (R2, R3, R4, R6, R7) | N |
| city | city | VARCHAR | Cardholder city | N | Y |
| state | state | VARCHAR | Cardholder state | N | Y |
| zip | zip | VARCHAR | Cardholder ZIP code, read as text | N | Y |
| lat | lat | DOUBLE | Cardholder home latitude | Y (R5) | Y |
| long | long | DOUBLE | Cardholder home longitude | Y (R5) | Y |
| city_pop | city_pop | BIGINT | Population of the cardholder's city | N | Y |
| merch_lat | merch_lat | DOUBLE | Merchant latitude | Y (R5) | N |
| merch_long | merch_long | DOUBLE | Merchant longitude | Y (R5) | N |
| unix_time | unix_time | BIGINT | Epoch seconds that do not match `ts` (see below). Kept only for the DQ check | N (do not use) | N |
| is_fraud | is_fraud | INTEGER | Label: 1 = fraud, 0 = normal. Used only to evaluate rules, never as a rule input | N (label) | N |
| is_scored | (derived) | BOOLEAN | True for rows that count in metrics. In `--period test` it is false for training rows loaded as history | N | N |

The location fields are marked sensitive because, combined, they can point to a person.
Reports and charts must not show card_id unmasked (use the last 4 digits) or any cardholder
location field at row level.

## Columns dropped at load (data minimisation)

| Raw name | Reason dropped |
|---|---|
| (unnamed first column) | Row index from the CSV export. It has no meaning |
| first | Cardholder first name. PII, not needed |
| last | Cardholder last name. PII, not needed |
| street | Cardholder street address. PII, not needed |
| gender | Protected attribute. Must not be used in rules or models |
| dob | Date of birth. Protected attribute and PII |
| job | Occupation. Personal attribute with no legitimate rule use |

These columns are declared in the `read_csv` call so the file parses, but they are never
selected, so they never reach any table.

## Known data issues

**unix_time does not match ts.** `outputs/dq/dq_unix_time_vs_ts.csv` shows:
- `unix_time` equals `ts` minus 7 calendar years for all 555,719 test rows.
- The same holds for 1,294,816 training rows.
- The remaining 1,859 training rows, all dated 2019-02-28, are exactly one day later than that.

It is a shifted copy of `ts` and adds no information. `ts` is the source of truth and
`unix_time` is not used anywhere.

**Merchant names all start with `fraud_`.** All 693 merchants in both files have this
prefix. It is a quirk of the generator, not a label, and carries no signal.

**The data is simulated.** Fraud is concentrated in narrow category and amount bands. For
example, every grocery_pos transaction from $300 to $500 in train is fraud
(1,127 of 1,127). Real card data is not this clean, so rule performance here will be
higher than it would be in production.

## Period summary (from outputs/dq)

| | Train | Test |
|---|---|---|
| Rows | 1,296,675 | 555,719 |
| Fraud rows | 7,506 (0.5789%) | 2,145 (0.386%) |
| First ts | 2019-01-01 00:00:18 | 2020-06-21 12:14:25 |
| Last ts | 2020-06-21 12:13:37 | 2020-12-31 23:59:34 |
| Distinct days | 537 | 194 |
| Distinct cards | 983 | 924 |
| Cards with any fraud | 762 | 218 |
| Distinct merchants | 693 | 693 |
| Distinct categories | 14 | 14 |
