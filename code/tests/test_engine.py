"""simulate(), max_safe_today(), currency conversion and linked_event_id resolution."""
from __future__ import annotations

import pytest

import engine as E
from conftest import build_data, d, event, profile

REQUEST_DATE = d(2025, 1, 1)


@pytest.fixture
def tiny():
    """Balance 1000, minimum 100.37. Hand-checkable path:
    rent 300 projected on the 2nd of each month (3 settled rows on the 2nd), pending card debit 200 settling 01-03,
    scheduled salary 500 on 01-05. A failed debit and a pending refund must be ignored."""
    E.set_config(variable_spending_mode="none", apply_message_effects=False)
    events = [
        event("e_rent1", "expense", "Monthly rent", "rent", "debit", 300.0, d(2024, 10, 2)),
        event("e_rent2", "expense", "Monthly rent", "rent", "debit", 300.0, d(2024, 11, 2)),
        event("e_rent3", "expense", "Monthly rent", "rent", "debit", 300.0, d(2024, 12, 2)),
        event("e_pend", "expense", "Pending card charge", "shopping", "debit", 200.0, d(2024, 12, 31), d(2025, 1, 3), status="pending"),
        event("e_sal", "income", "Next confirmed salary", "salary", "credit", 500.0, d(2025, 1, 5), status="scheduled"),
        event("e_fail", "expense", "Failed utility debit", "utilities", "debit", 999.0, d(2025, 1, 10), status="failed"),
        event("e_refund", "refund", "Pending merchant refund", "shopping", "credit", 50.0, d(2024, 12, 30), d(2025, 1, 4), status="pending"),
    ]
    return build_data([profile(balance=1000.0, minimum=100.37)], events)


def test_simulate_exact_daily_balances(tiny):
    safe, low, daily = E.simulate("user_t", REQUEST_DATE, data=tiny)
    balances = dict(daily)
    assert len(daily) == 91                      # request_date .. request_date + 90 inclusive
    assert daily[0] == (d(2025, 1, 1), 1000.0)
    expected = {d(2025, 1, 1): 1000.0, d(2025, 1, 2): 700.0, d(2025, 1, 3): 500.0, d(2025, 1, 4): 500.0,
                d(2025, 1, 5): 1000.0, d(2025, 1, 10): 1000.0, d(2025, 2, 1): 1000.0, d(2025, 2, 2): 700.0,
                d(2025, 3, 1): 700.0, d(2025, 3, 2): 400.0, d(2025, 4, 1): 400.0}
    for day, bal in expected.items():
        assert balances[day] == bal, day
    assert daily[-1] == (d(2025, 4, 1), 400.0)
    assert (safe, low) == (True, 400.0)


def test_simulate_with_payment_and_breach(tiny):
    ok, low, daily = E.simulate("user_t", REQUEST_DATE, [(REQUEST_DATE, 350.0)], data=tiny)
    assert not ok and low == 50.0                # 400 - 350 < 100.37
    assert dict(daily)[d(2025, 1, 2)] == 350.0


@pytest.mark.parametrize("fast", [True, False])
def test_max_safe_today_is_the_true_boundary(tiny, fast):
    E.set_config(use_fast_path=fast)
    safe = E.max_safe_today("user_t", REQUEST_DATE, 1000.0, data=tiny)
    assert safe == pytest.approx(299.63, abs=1e-9)   # lowest balance 400 - minimum 100.37
    assert E.simulate("user_t", REQUEST_DATE, [(REQUEST_DATE, safe)], data=tiny)[0]
    assert not E.simulate("user_t", REQUEST_DATE, [(REQUEST_DATE, round(safe + 0.01, 2))], data=tiny)[0]


def test_max_safe_today_is_capped_at_requested(tiny):
    assert E.max_safe_today("user_t", REQUEST_DATE, 250.0, data=tiny) == 250.0
    assert E.earliest_full_date("user_t", REQUEST_DATE, 250.0, data=tiny) == REQUEST_DATE
    assert E.earliest_full_date("user_t", REQUEST_DATE, 1000.0, data=tiny) is None


def test_currency_conversion_both_ways():
    rate_day = d(2025, 10, 15)
    fx = {("USD", "INR"): {rate_day: 83.33}}
    assert E.fx_rate(fx, "USD", "INR", rate_day) == 83.33
    assert E.fx_rate(fx, "INR", "USD", rate_day) == pytest.approx(1 / 83.33)
    assert E.to_home(fx, 100.0, "USD", "INR", rate_day) == 8333.0
    assert E.to_home(fx, 8333.0, "INR", "USD", rate_day) == 100.0
    assert E.fx_rate(fx, "USD", "INR", d(2025, 10, 20)) == 83.33   # nearest prior rate when the day has none


def test_real_rate_row_converts_image_amount(real_data):
    assert real_data.fx[("USD", "INR")][d(2025, 10, 1)] == 83.33
    taxi = real_data.events["event_7307"]            # USD 33.50 read from image_12, settles 2025-10-01
    assert taxi.currency == "USD" and taxi.amount == 33.50
    assert taxi.amount_home == pytest.approx(33.50 * 83.33, abs=0.01)


# (parent, child, include child in forecast?, reason prefix) — one real chain per pattern
CHAINS = [
    ("event_98", "event_99", False, "historical"),        # expense settled -> refund settled
    ("event_100", "event_101", False, "historical"),      # authorization cancelled -> purchase settled
    ("event_1784", "event_1785", False, "pending credit"),  # expense settled -> refund pending
    ("event_1855", "event_1856", False, "non-cash"),      # investment purchase -> unrealized valuation
    ("event_8575", "event_8576", True, "scheduled debit"),  # failed bill payment -> scheduled retry
    ("event_7305", "event_7306", False, "historical"),    # investment purchase -> sale proceeds settled
    ("event_12708", "event_12709", True, "pending debit"),  # settled charge -> possible duplicate pending
]


@pytest.mark.parametrize("parent_id,child_id,include,reason", CHAINS)
def test_linked_chain_resolution(real_data, parent_id, child_id, include, reason):
    parent, child = real_data.events[parent_id], real_data.events[child_id]
    assert child.linked_event_id == parent_id
    assert parent.superseded_by == child_id                  # the later event supersedes the earlier one
    request = next(r for r in real_data.requests.values() if r.user_id == child.user_id)
    _, end = E.forecast_window(request.request_date)
    parent_in, parent_reason = E.future_row_role(parent, request.request_date, end, real_data)
    child_in, child_reason = E.future_row_role(child, request.request_date, end, real_data)
    assert not parent_in and parent_reason.startswith("superseded by") or parent_reason in ("cancelled", "failed")
    assert child_in is include
    assert child_reason.startswith(reason)


def test_possible_duplicate_flag_excludes_duplicate(real_data):
    child = real_data.events["event_12709"]
    request = next(r for r in real_data.requests.values() if r.user_id == child.user_id)
    _, end = E.forecast_window(request.request_date)
    E.set_config(possible_duplicate_pending_debit="exclude")
    assert E.future_row_role(child, request.request_date, end, real_data) == (False, "possible duplicate of event_12708")
