"""Exhaustive, deterministic plan search (no LLM).

Candidates: full_payment today | every supplied installment option (exact schedule) | partial_payment
(amount_safe_to_pay today + remainder on earliest_date_for_full_payment) | wait (full on earliest date), each crossed
with every subset of up to 3 allowed spending changes. Eligibility is filtered first, every survivor is simulated,
and the safe ones are ranked with the spec's six tie-breakers as one tuple key. not_recommended is the fallback.
"""
from __future__ import annotations

import itertools
import math
from datetime import date

import engine as E
import explain

NO_OPTION = 10 ** 9


# ---------------------------------------------------------------- eligibility
def within_max_installment_months(option, max_months: int | None) -> bool:
    if max_months is None:
        return False
    if E.CONFIG["installment_months_basis"] == "span_months":
        span_days = (option.number_of_payments - 1) * (option.payment_frequency_days or 0)
        return math.ceil(span_days / 30.44) <= max_months
    return option.number_of_payments <= max_months


def base_plans(req, data, safe: float, earliest: date | None) -> list[dict]:
    profile = data.profiles[req.user_id]
    methods = set(profile.payment_methods)
    options = data.options_by_request.get(req.request_id, [])
    rd, amount = req.request_date, req.requested_amount
    plans = []
    if "full_payment" in methods:
        full = next((o for o in options if o.payment_method == "full_payment"), None)
        plans.append({"method": "full_payment", "payments": [(rd, amount)], "total_paid": amount,
                      "option_id": full.payment_option_id if full else ""})
    if ("partial_payment" in methods and req.allows_partial_payment and 0 < safe < amount
            and earliest is not None and earliest <= req.desired_completion_date):
        plans.append({"method": "partial_payment", "payments": [(rd, safe), (earliest, round(amount - safe, 2))],
                      "total_paid": amount, "option_id": ""})
    if "full_payment" in methods and earliest is not None and earliest > rd:
        plans.append({"method": "wait", "payments": [(earliest, amount)], "total_paid": amount, "option_id": ""})
    if "installments" in methods:
        for o in options:
            if o.payment_method == "installments" and within_max_installment_months(o, profile.max_installment_months):
                plans.append({"method": "installments", "payments": o.schedule(), "total_paid": o.total_payable_amount,
                              "option_id": o.payment_option_id})
    return plans


def change_candidates(req, data) -> list[tuple]:
    """Every flexible expense the user permits, monthly series and irregular groups alike: stop (stop_ok category)
    or reduce_to minimum_allowed_amount (reduce_ok category)."""
    profile = data.profiles[req.user_id]
    out = []
    for s in (E.detect_series(req.user_id, req.request_date, data)
              + E.irregular_flexible_series(req.user_id, req.request_date, data)):
        if s.direction != "debit":
            continue
        eid = s.latest.event_id
        if s.flexibility in ("stoppable", "reducible_or_stoppable") and s.category in profile.stop_ok:
            out.append(("stop", eid))
        if (s.flexibility in ("reducible", "reducible_or_stoppable") and s.category in profile.reduce_ok
                and s.min_allowed_home is not None):
            target = round(E.default_reduce_amount(s), 2)
            if target < s.amount_home - 0.005:
                out.append(("reduce_to", eid, target))
    return out


def subsets(candidates: list[tuple], k: int):
    if k == 0:
        yield ()
        return
    for combo in itertools.combinations(candidates, k):
        if len({c[1] for c in combo}) == k:  # stop and reduce of the same event are mutually exclusive
            yield combo


# ---------------------------------------------------------------- safety + ranking
def simulate_plan(req, payments: list[tuple], changes: tuple, data):
    _, end = E.forecast_window(req.request_date)
    pays = payments if E.CONFIG["payments_beyond_horizon"] == "count" else [(d, a) for d, a in payments if d <= end]
    return E.simulate(req.user_id, req.request_date, pays, list(changes), data=data)


def rank_key(c: dict) -> tuple:
    n = len(c["changes"])
    return (
        0 if c["completes"] else 1,                          # 1 completes by desired_completion_date
        1 if n else 0,                                       # 2 requires no spending changes
        n if E.CONFIG["rank_changes_by_count"] else 0,       #   (fewer changes, when changes are needed)
        round(c["total_paid"], 2),                           # 3 lowest total paid
        c["payments"][0][0],                                 # 4 earlier start
        len(c["payments"]),                                  # 5 fewer payments
        E.id_num(c["option_id"]) if c["option_id"] else NO_OPTION,  # 6 lowest payment_option_id
        tuple(sorted(map(str, c["changes"]))),               # deterministic final order
    )


def search(req, data) -> dict:
    safe = E.max_safe_today(req.user_id, req.request_date, req.requested_amount, data)
    earliest = E.earliest_full_date(req.user_id, req.request_date, req.requested_amount, data)
    plans = base_plans(req, data, safe, earliest)
    candidates = change_candidates(req, data)
    require = E.CONFIG["require_completion_by_desired_date"]
    found = []
    for k in range(min(E.CONFIG["max_spending_changes"], len(candidates)) + 1):
        for plan in plans:
            completes = plan["payments"][-1][0] <= req.desired_completion_date
            if require and not completes:
                continue
            for combo in subsets(candidates, k):
                ok, low, daily = simulate_plan(req, plan["payments"], combo, data)
                if ok:
                    found.append({**plan, "changes": combo, "completes": completes, "daily": daily})
        if any(c["completes"] for c in found) and (E.CONFIG["rank_changes_by_count"] or k == 0):
            break
    winner = min(found, key=rank_key) if found else None
    return {"safe": safe, "earliest": earliest, "winner": winner, "candidates": found, "plans": plans,
            "change_candidates": candidates}


# ---------------------------------------------------------------- output row
def format_changes(changes: tuple) -> str:
    if not changes:
        return "none"
    ordered = sorted(changes, key=lambda c: (0 if c[0] == "stop" else 1, E.id_num(c[1])))
    return "|".join(f"stop:{c[1]}" if c[0] == "stop" else f"reduce_to:{c[1]}:{E.format_amount(c[2])}" for c in ordered)


def recommend(req, data=None) -> dict:
    data = data or E.get_data()
    result = search(req, data)
    safe, earliest, winner = result["safe"], result["earliest"], result["winner"]
    fmt = E.format_amount
    if winner is None:
        _, _, daily = E.simulate(req.user_id, req.request_date, data=data)
        method, payments, changes, status = "not_recommended", [], (), "not_affordable"
    else:
        method, payments, changes, daily = winner["method"], winner["payments"], winner["changes"], winner["daily"]
        if method == "full_payment" and not changes:
            status = "affordable_now"
        elif method == "wait":
            status = "affordable_later"
        else:
            status = "affordable_with_plan"
    return {
        "amount_safe_to_pay": fmt(safe),
        "affordability_status": status,
        "recommended_payment_method": method,
        "payment_plan": "|".join(f"{d.isoformat()}:{fmt(a)}" for d, a in payments) if payments else "none",
        "earliest_date_for_full_payment": earliest.isoformat() if earliest else "",
        "spending_changes_needed": format_changes(changes),
        "decision_explanation": explain.explain(req, data, method, payments, changes, safe, earliest, daily),
    }
