# Rule register

This is the current state of every rule. It is updated with each version change; history
is in [CHANGELOG.md](../CHANGELOG.md).
- **Train figures:** from the training period (2019-01-01 to 2020-06-21, 537 days, 7,506
  fraud transactions), in `outputs/train/`.
- **Test figures:** added after post-deployment validation (PVT).
- **Tuning evidence:** in [tuning_report.md](tuning_report.md).
- **Owner:** the project author. Approval: [TBD] (maker/checker sign-off in Phase 4).

**Rule set v2:** approved and frozen on 2026-11-17. The previous rule set (R1 to R7 at
v1.0/v1.1, before tuning) can be reproduced from git tag `rules-v1.1`.

| Rule | Frozen version (set v2) | Status |
|---|---|---|
| R1 | 1.1 | retired |
| R2 | 1.0 | retired |
| R3 | 2.0 | active |
| R4 | 2.0 | active |
| R5 | 1.0 | retired |
| R6 | 2.0 | active |
| R7 | 2.0 | active |
| R8 | 1.0 (risk list v1) | shadow |

## Summary (train)

| ID | Version | Status | Action | Alerts/day | Precision | Txn recall | Value detection | Unique fraud | UAT cases |
|---|---|---|---|---|---|---|---|---|---|
| R1 | 1.1 | Retired | ALERT | 1.11 | 21.61% | 1.72% | 2.11% | 5 | UAT-R1-01 to 08 |
| R2 | 1.0 | Retired | STEP_UP | 51.91 | 9.36% | 34.75% | 55.73% | 39 | UAT-R2-01 to 04 |
| R3 | 2.0 | Active | HOLD_CONFIRM | 8.78 | 63.37% | 39.82% | 68.38% | 16 | UAT-R3-01 to 08 |
| R4 | 2.0 | Active | ALERT | 20.76 | 46.70% | 69.37% | 93.31% | 1,213 | UAT-R4-01 to 08 |
| R5 | 1.0 | Retired | ALERT | 563.97 | 0.58% | 23.27% | 23.60% | 271 | UAT-R5-01 to 03 |
| R6 | 2.0 | Active | STEP_UP | 6.09 | 42.21% | 18.40% | 32.37% | 0 | UAT-R6-01 to 05 |
| R7 | 2.0 | Active | HOLD_CONFIRM | 23.60 | 33.01% | 55.74% | 63.91% | 1,093 | UAT-R7-01 to 10 |
| R8 | 1.0 | Shadow | BLOCK / HOLD_CONFIRM by tier | not scored on train (in-sample) | | | | | UAT-R8-01 to 04 |
| Active set | v2 | | | 37.80 | 31.40% | 84.92% | 98.04% | | |

- **Unique fraud:** for an active rule, fraud no other active rule catches. For a retired
  rule, fraud it would add if reinstated.
- **Retired rules** are still computed at their last version so their volume can be
  monitored. They do not alert.

## R1 Card velocity: retired
- **Version:** 1.1 (status retired in rule set v2, 2026-11-17)
- **Business intent:** catch rapid repeated use of a card, typical of card testing or a
  stolen card being drained.
- **Logic:**
  ```
  count = card's transactions with ts in [ts - 60 min, ts], including this one;
          same-second transactions count only if earlier in (ts, trans_num) order
  IF count >= 5 THEN ALERT ELSE no action
  ```
- **Why retired:**
  - Windows of 120 and 180 minutes only lower precision.
  - In the tuned set it adds 466 alerts for 5 fraud.
  - Fraud in this data arrives over about 45 hours, not minutes.
- **Revisit if** the portfolio shows card-testing patterns.
- **Fields:** card_id, ts, trans_num.
- **Version history:**
  - **1.0:** initial.
  - **1.1:** window ends at the current row (DEF-01). 20 train rows' features changed,
    0 flags flipped.
  - **Retired in set v2.**

## R2 Amount spike: retired
- **Version:** 1.0 (status retired in rule set v2)
- **Business intent:** catch a transaction far larger than the card's normal spend.
- **Logic:**
  ```
  avg = average amt of the card's previous 30 transactions (excluding this one)
  IF card has at least 1 prior transaction AND amt > 5 x avg THEN STEP_UP ELSE no action
  ```
- **Why retired:** even the best tuned version (5 times with a $500 floor) adds 4,573
  alerts for 25 fraud on top of R3, R4, R6 and R7.
- **Fields:** card_id, ts, trans_num, amt.
- **Known gap:** a card's first-ever transaction can't fire (UAT-R2-01).

## R3 Late-night high value: active
- **Version:** 2.0 (2026-11-17)
- **Business intent:** high-value spend at hours when the cardholder is usually inactive.
- **Logic:**
  ```
  IF (hour >= 22 OR hour < 4) AND amt > 600 THEN HOLD_CONFIRM ELSE no action
  ```
- **Threshold and rationale:**
  - The hours come from the EDA: 84.76% of train fraud falls in this window.
  - Amount 500 to 600: in the final set the $500 to $600 band adds 916 alerts for 27
    fraud.
  - Kept despite 16 unique catches because it fires on the first alerted fraud
    transaction for 246 of 755 detected cards, turning a post-event ALERT into a real-time
    hold.
- **Fields:** ts, amt.
- **Version history:**
  - **1.0:** amt > 500.
  - **2.0:** amt > 600.

## R4 Risky category + amount: active
- **Version:** 2.0 (2026-11-17)
- **Business intent:** high-value spend in the categories where fraud concentrates.
- **Logic:**
  ```
  min_amt = lookup(category): shopping_net 600, misc_net 600, shopping_pos 600, grocery_pos 250
  IF category in lookup AND amt > min_amt THEN ALERT ELSE no action
  ```
- **Threshold and rationale:**
  - grocery_pos 300 to 250 adds 613 fraud for 798 alerts.
  - The other three, 500 to 600, remove 1,877 alerts and lose 3 fraud.
  - No upper caps (simulator artifact).
- **Fields:** category, amt.
- **Version history:**
  - **1.0:** 500 / 500 / 500 / 300.
  - **2.0:** 600 / 600 / 600 / 250.

## R5 Distance anomaly: retired
- **Version:** 1.0 (status retired in rule set v2)
- **Business intent:** spend far from the cardholder's home location.
- **Logic:**
  ```
  IF haversine(lat, long, merch_lat, merch_long) > 100 km THEN ALERT ELSE no action
  ```
- **Why retired:**
  - Precision is 0.53% to 0.58% at every distance from 25 to 125 km, against a train fraud
    rate of 0.579%.
  - Net benefit is -$572,954.10 at its v1 setting.
- **Fields:** lat, long, merch_lat, merch_long (cardholder location is sensitive).

## R6 New merchant + high amount: active
- **Version:** 2.0 (2026-11-17)
- **Business intent:** a card with an established pattern suddenly spends a large amount at
  a merchant it has never used.
- **Logic:**
  ```
  IF first transaction of this card at this merchant
     AND card has >= 10 prior transactions
     AND amt > 750
  THEN STEP_UP ELSE no action
  ```
- **Threshold and rationale:**
  - Y 300 to 750: precision rises from 17.14% to 42.21% and alerts fall from 23.15 to
    6.09 per day.
  - N barely matters in the sweep.
- **Status decision (approved rule):** shadow if it loses 0 fraud AND is the first alert for
  fewer than 1% of detected cards; otherwise active.
  - Removing it saves 237 alerts and loses 0 fraud ($0).
  - It fires on the first alerted fraud for 129 of 755 detected cards (17.09%), and sets the
    first response for 28 (3.71%). Above 1%, so it stays **active**.
  - Under the stricter reading "only rule on the first alert" it would be 0% and shadow.
  - It is the first candidate for shadow at the next review.
- **Fields:** card_id, merchant, ts, trans_num, amt.
- **Known gap:** a card's first-ever transaction can't fire (UAT-R6-05).
- **Version history:**
  - **1.0:** Y = 300.
  - **2.0:** Y = 750.

## R7 Spend burst: active
- **Version:** 2.0 (2026-11-17)
- **Business intent:** a card's spend over two days jumps far above its normal level,
  matching the multi-transaction spree pattern in the EDA.
- **Logic:**
  ```
  spend_48h = card's spend with ts in [ts - 48 h, ts], including this transaction;
              same-second transactions count only if earlier in (ts, trans_num) order
  baseline  = average daily spend over the card's previous 30 active days (current day excluded)
  IF card has >= 7 prior active days AND spend_48h > 5 x 2 x baseline THEN HOLD_CONFIRM
  ELSE no action
  ```
- **Threshold and rationale:**
  - 24 h with 3 times (178.01 alerts per day, 6.09% precision) moved to 48 h with 5 times
    (23.60 per day, 33.01%).
  - The 48-hour window covers the roughly 45-hour fraud spree.
  - A spend floor changes little at 48 h, so there is none.
  - 14 minimum days instead of 7 loses recall in every setting.
- **Fields:** card_id, ts, trans_num, amt.
- **Version history:**
  - **1.0:** 24 h, 3 times.
  - **1.1:** window ends at the current row (DEF-02).
  - **2.0:** 48 h, 5 times two days of baseline; column renamed from r7_spend_burst_24h to
    r7_spend_burst.

## R8 Risk-list hit: shadow
- **Version:** 1.0 (2026-11-17), list v1
- **Business intent:** stop or hold payments at merchants with a history of fraud.
- **Logic:**
  ```
  tier = lookup(merchant) in rules/risk_lists/merchant_risk_v1.csv
  IF tier = very_high THEN BLOCK
  ELSE IF tier = high THEN HOLD_CONFIRM
  ELSE no action
  ```
- **List criteria (train only):**
  - at least 500 train transactions and at least 10 fraud
  - fraud rate at least 4.0 times the train base rate: very_high (2 merchants)
  - 3.5 to 4.0 times: high (6 merchants)
- **Why shadow:**
  - Merchant-level fraud is weak in this data (highest rate 2.57%), and the listed merchants
    are in categories R4 already covers.
  - Its train precision is in-sample.
  - It is scored on test only; promotion needs PVT evidence.
- **Fields:** merchant.
- **Known gap:** exact name match (UAT-R8-04); production would key on a merchant ID.
