"""Planner tie-breakers: cases where only rule 3 (total paid) or only rule 6 (payment_option_id) decides."""
from __future__ import annotations

import engine as E
import planner
from conftest import build_data, d, profile

REQUEST_DATE = d(2025, 1, 1)


def installment_case(options):
    E.set_config(variable_spending_mode="none")
    request = E.Request("request_t", "user_t", REQUEST_DATE, "purchase", 300.0, d(2025, 6, 1), False, "test")
    data = build_data([profile(balance=100000.0, minimum=100.0, methods=("installments",), max_months=12)],
                      requests=[request], options=options)
    return request, data


def option(option_id, amount, total, first=d(2025, 1, 8), n=3, every=30):
    return E.PaymentOption(option_id, "request_t", "installments", amount, n, first, every, round(total - 300.0, 2), total)


def test_rule_3_lowest_total_paid_wins():
    request, data = installment_case([option("payment_option_1", 110.0, 330.0), option("payment_option_2", 100.0, 300.0)])
    result = planner.search(request, data)
    keys = {c["option_id"]: planner.rank_key(c) for c in result["candidates"]}
    assert set(keys) == {"payment_option_1", "payment_option_2"}          # both safe, both eligible
    a, b = keys["payment_option_1"], keys["payment_option_2"]
    assert [i for i in range(len(a)) if a[i] != b[i]] == [3, 6]           # only total paid and option id differ
    assert result["winner"]["option_id"] == "payment_option_2"            # rule 3 beats the lower id (rule 6)
    assert planner.recommend(request, data)["payment_plan"] == "2025-01-08:100|2025-02-07:100|2025-03-09:100"


def test_rule_6_lowest_payment_option_id_wins():
    request, data = installment_case([option("payment_option_7", 100.0, 300.0), option("payment_option_3", 100.0, 300.0)])
    result = planner.search(request, data)
    keys = {c["option_id"]: planner.rank_key(c) for c in result["candidates"]}
    a, b = keys["payment_option_7"], keys["payment_option_3"]
    assert [i for i in range(len(a)) if a[i] != b[i]] == [6]              # identical except the option id
    assert result["winner"]["option_id"] == "payment_option_3"


def test_rule_1_deadline_beats_everything():
    E.set_config(require_completion_by_desired_date=False)
    late = option("payment_option_1", 100.0, 300.0, first=d(2025, 5, 20))   # last payment after 2025-06-01
    on_time = option("payment_option_9", 110.0, 330.0)
    request, data = installment_case([late, on_time])
    assert planner.search(request, data)["winner"]["option_id"] == "payment_option_9"


def test_installments_over_max_months_are_ineligible():
    request, data = installment_case([option("payment_option_1", 25.0, 300.0, n=12), option("payment_option_2", 20.0, 300.0, n=15)])
    ids = {p["option_id"] for p in planner.base_plans(request, data, 300.0, REQUEST_DATE)}
    assert ids == {"payment_option_1"}
