"""Template explanations filled from engine values (no LLM, no free text).

Sentence shapes follow dataset/sample_requests.csv; a second sentence states the concrete forecast facts
(balance today, the binding low point and its date).
"""
from __future__ import annotations

from datetime import date

import engine as E


def money(currency: str, x: float) -> str:
    return f"{currency} {x:,.0f}" if abs(x - round(x)) < 0.005 else f"{currency} {x:,.2f}"


def long_date(d: date) -> str:
    return f"{d.day} {d.strftime('%B')} {d.year}"


def change_text(changes: tuple, data, currency: str) -> str:
    ordered = sorted(changes, key=lambda c: (0 if c[0] == "stop" else 1, E.id_num(c[1])))
    parts = []
    for c in ordered:
        name = data.events[c[1]].description.lower() if c[1] in data.events else c[1]
        parts.append(f"stop the {name}" if c[0] == "stop" else f"reduce the {name} to {money(currency, c[2])}")
    text = " and ".join(parts)
    return text[:1].upper() + text[1:]


def low_point(daily: list[tuple]) -> tuple[date, float] | None:
    return min(daily, key=lambda t: (t[1], t[0])) if daily else None


def explain(req, data, method: str, payments: list, changes: tuple, safe: float, earliest: date | None,
            daily: list[tuple]) -> str:
    profile = data.profiles[req.user_id]
    cur = profile.home_currency
    m = lambda x: money(cur, x)  # noqa: E731
    minimum, amount = m(profile.minimum_balance), m(req.requested_amount)
    low = low_point(daily)
    facts = (f" Balance today is {m(profile.balance)}; the lowest projected balance is {m(low[1])} on {long_date(low[0])}."
             if low else f" Balance today is {m(profile.balance)}.")
    prefix = f"{change_text(changes, data, cur)}, then " if changes else ""

    if method == "full_payment":
        head = f"{prefix}pay {amount} today." if changes else f"Pay {amount} today."
        tail = f" This leaves at least {minimum} available." if changes else f" This leaves at least {minimum} available over the next 90 days."
        return head[:1].upper() + head[1:] + tail + facts
    if method == "installments":
        head = f"{prefix}use {len(payments)} installments of {m(payments[0][1])}, starting {long_date(payments[0][0])}."
        return head[:1].upper() + head[1:] + f" This leaves at least {minimum} available." + facts
    if method == "partial_payment":
        (d1, a1), (d2, a2) = payments
        head = f"{prefix}pay {m(a1)} today and the remaining {m(a2)} on {long_date(d2)}."
        return (head[:1].upper() + head[1:] + f" This completes the full request and keeps the {minimum} minimum protected."
                + facts)
    if method == "wait":
        d = payments[0][0]
        return (f"Pay {amount} in full on {long_date(d)}. Paying earlier would take the balance below the {minimum} minimum."
                f" At most {m(safe)} is safe to pay today from a balance of {m(profile.balance)}.")
    methods = set(profile.payment_methods)
    if safe > 0 and req.allows_partial_payment and methods == {"partial_payment"}:
        head = (f"Do not proceed with the {amount} request. Although {m(safe)} is available today, the full amount "
                f"cannot be completed safely within 90 days.")
    else:
        head = (f"Do not make this payment by {long_date(req.desired_completion_date)}. None of the available options "
                f"keeps the {minimum} minimum protected.")
    tail = (f" Balance today is {m(profile.balance)}; even without this payment the lowest projected balance is "
            f"{m(low[1])} on {long_date(low[0])}." if low else "")
    return head + tail
