"""UAT: each case in tests/uat_cases.csv runs through sql/10 on its own rows only."""

from collections import Counter

import pytest

from uat import RULE_COLUMNS, load_cases, parse_expected, run_case, target_row

CASES = load_cases()


@pytest.mark.parametrize("test_id", sorted(CASES))
def test_uat_case(test_id):
    rows = CASES[test_id]
    target = target_row(rows)
    expected = parse_expected(target["expected_hit"])

    actual = run_case(rows)

    # `is` rather than ==: a NULL flag (None) must fail, not pass as falsy.
    assert actual is expected, f"{test_id}: {target['description']} -> got {actual}"


def test_every_rule_has_at_least_three_cases():
    per_rule = Counter(target_row(rows)["rule"] for rows in CASES.values())
    for rule in RULE_COLUMNS:
        assert per_rule[rule] >= 3, f"{rule} has {per_rule[rule]} UAT cases"


def test_every_case_has_one_target_and_a_known_rule():
    for test_id, rows in CASES.items():
        target = target_row(rows)
        assert target["rule"] in RULE_COLUMNS, test_id
        assert all(r["rule"] == target["rule"] for r in rows), test_id


def test_required_brief_cases_present():
    required = ["UAT-R1-01", "UAT-R1-02", "UAT-R1-03", "UAT-R2-01", "UAT-R3-01", "UAT-R3-02", "UAT-R3-03"]
    missing = [t for t in required if t not in CASES]
    assert not missing, f"missing required cases: {missing}"
