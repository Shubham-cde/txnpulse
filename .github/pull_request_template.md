## Rule change

| Field | Value |
|---|---|
| Rule ID | |
| Version change | e.g. 2.0 -> 2.1 |
| Change type | threshold / logic / status (active, shadow, retired) / new rule / risk list |
| Business intent | Why the change is needed, in one or two sentences |

## Evidence

### Backtest on train (before vs after)
Source files in `outputs/train/` (run `python run_all.py`).

| Metric | Before | After |
|---|---|---|
| Alerts per day (rule / active set) | | |
| Cases per day (active set) | | |
| Precision | | |
| Transaction recall | | |
| Value detection | | |
| Unique fraud catches (leave-one-out) | | |

### Post-deployment validation (test period)
- PVT result for the current version (link to `reports/pvt_report.md` section):
- If this change was prompted by PVT findings, test-period figures for the new version are an
  **impact estimate, not out-of-sample validation**. State which figures are affected.

### UAT evidence
- [ ] Boundary cases added or updated in `tests/uat_cases.csv` (list test IDs):
- [ ] `python -m pytest tests` passes (paste the summary line):
- [ ] `reports/uat_report.md` refreshed with `python src/run_uat.py`

## Workload impact
- Alerts per day and cases per day for the active set, before and after, against the alert
  budget (50 per day):
- Peak month (alerts per day, cases per day):
- Customer-facing actions (STEP_UP, HOLD_CONFIRM, BLOCK) per day, before and after:

## Rollback plan
- How to revert (for example, revert this PR, or set the status back in `rule_catalogue`):
- How to confirm the rollback (which output should return to which value):

## Documentation
- [ ] `reports/rule_register.md` updated (version, status, rationale, performance)
- [ ] `CHANGELOG.md` entry added
- [ ] No test-period data used to choose any threshold

## Maker / checker

| Role | Name | Date | Decision |
|---|---|---|---|
| Maker (author) | | | |
| Checker (reviewer, must not be the maker) | | | |
