"""Deterministic cash-flow engine for "Buy or Wait?".

Pure Python (stdlib only). No LLM, no network. Every ambiguous rule is a flag in CONFIG.

    python code/engine.py                      # ledgers for the first 3 sample requests
    python code/engine.py request_06 user_02   # ledgers for specific requests / users
"""
from __future__ import annotations

import calendar
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "dataset"
IMAGE_AMOUNTS_PATH = Path(__file__).resolve().parent / "image_amounts.json"

# =====================================================================================
# CONFIG - every ambiguous rule lives here. See code/DATA_NOTES.md for both readings.
# =====================================================================================
CONFIG = {
    # ---- forecast window ----
    "horizon_days": 90,
    "forecast_starts_day_0_or_1": 0,          # 0: ledger items dated request_date are applied; 1: start at request_date+1
    "forecast_includes_day_90": True,         # window end = request_date+90 (True) or +89 (False)
    "earliest_date_window_anchor": "request_date",  # "request_date" | "payment_date" (re-anchor 90 days at payment)

    # ---- intra-day ordering and the safety check ----
    "salary_applied_before_expenses_same_day": True,  # credits before debits within a day
    "min_balance_checked_after_payment": True,  # True: check after every movement; False: end of day only
    "check_opening_balance": True,            # opening balance itself must be >= minimum
    "unsafe_if_equal_to_minimum": False,      # False: balance == minimum is still safe

    # ---- amounts ----
    "rounding_mode": "floor_2dp",             # floor_2dp | round_2dp | floor_int | round_int
    "binary_search_precision": 0.0005,
    "amount_format": "int_if_whole_else_2dp",  # int_if_whole_else_2dp | always_2dp
    "use_fast_path": True,                    # one-walk margin profile instead of binary search / 91 simulations

    # ---- currency ----
    "fx_date_field": "settlement_date",       # settlement_date | event_date
    "fx_allow_inverse": True,                 # use 1/rate when only the reverse pair exists
    "fx_missing_rate": "nearest_prior",       # nearest_prior | nearest | error
    "fx_round_2dp": True,

    # ---- status / lifecycle handling for dated future rows ----
    "include_pending_debits": True,
    "pending_debits_reserved_immediately": False,  # True: pending debit leaves spendable balance on request_date; False: on its settlement_date
    "include_pending_credits": False,
    "include_scheduled_debits": True,
    "include_scheduled_credits": True,        # e.g. "Next confirmed salary"
    "possible_duplicate_pending_debit": "include",  # include (safer) | exclude (treat as duplicate record)
    "linked_resolution": "child_supersedes_parent",  # child_supersedes_parent | none
    "blank_amount_policy": "override_else_skip",  # override_else_skip | override_else_error

    # ---- recurring debits (monthly series) ----
    "recurring_expense_event_types": ["expense", "subscription", "debt_payment"],
    "recurring_min_occurrences": 3,
    "recurring_max_dom_spread": 0,            # allowed spread (days) in day-of-month across occurrences
    "recurring_require_one_per_month": True,
    "recurring_max_staleness_days": 35,       # debit series ended if last occurrence is older than this
    "recurring_amount_basis": "last",         # last | mean | max
    "recurring_day_basis": "mode",            # mode | last
    "project_recurring_from": "request_date",  # request_date: drop occurrences in the history gap | last_row_date: catch them up on day 0
    "dedupe_projection_against_explicit": "credits_only",  # credits_only | all | off
    "dedupe_window_days": 7,

    # ---- income projection ----
    "recurring_include_income": True,
    "income_series_key": "category_dom",      # category_dom | description
    "income_projection_categories": ["salary"],
    "recurring_min_occurrences_income": 2,
    "salary_projection_amount": "last_occurrence",  # last_occurrence | median_of_last_n | mean_of_last_n
    "salary_projection_n": 3,                 # 3 | 6 | "all"
    "salary_projection_day": "same_day_of_month",  # same_day_of_month | same_interval
    "stopped_income_cutoff_days": 35,         # income series ended after this many days of silence
    "project_irregular_income": False,        # commission / bonus / gig / freelance income projected?
    "irregular_income_keywords": ["commission", "bonus", "arrears", "prize", "reimbursement", "payout", "earnings",
                                  "invoice", "project", "contract", "freelance", "independent", "retainer",
                                  "milestone", "seasonal", "temporary", "peak-season"],

    # ---- variable (irregular) spending ----
    "variable_spending_mode": "none",         # none | daily_average | replay_last_period | monthly_total_spread
    "variable_lookback_days": 90,             # 30 | 60 | 90 | "all_history"
    "variable_window_anchor": "request_date",  # request_date | last_history_date
    "variable_spending_categories": "protected_only",  # protected_only | all | all_except_flexible
    "variable_average_basis": "mean",         # mean | median (median of 30-day block totals)
    "variable_applied_as": "even_daily_amount",  # even_daily_amount | same_weekday_pattern | same_day_of_month_pattern
    "description_amount_basis": "mean",       # description_monthly mode: mean | last | max per description series
    # flexible expenses that are NOT monthly series (e.g. irregular reducible dining):
    # none: not forecast individually | monthly_mean: mean amount on the last row's day each month |
    # monthly_mean_from_start: mean amount on the forecast start day, then monthly
    "irregular_flexible_projection": "none",

    # ---- spending changes ----
    "spending_change_event_ref": "any_occurrence",  # latest_occurrence | any_occurrence
    "reduce_to_uses_minimum_cut": True,       # True: reduce to minimum_allowed_amount; False: reduce_to_zero

    # ---- messages (code/message_rules.py) ----
    "apply_message_effects": True,
    "message_visibility": "sent_on_or_before_request",  # sent_on_or_before_request | all
    "unsupported_income_policy": "exclude",   # exclude (spec) | include_confirmed
    "unsupported_expense_policy": "exclude",  # include | exclude
    "temporary_income_change_scope": "next_only",  # next_only | all_future (temporary / reduced / next-payroll pay)
    "count_one_time_arrears": False,          # one-off arrears in the next payroll counted as income?

    # ---- planner (code/planner.py) ----
    "require_completion_by_desired_date": True,  # True: plans finishing after the deadline are not candidates
    "installment_months_basis": "number_of_payments",  # number_of_payments | span_months
    "payments_beyond_horizon": "ignore",      # ignore: only payments inside the 90-day window are simulated | count
    "rank_changes_by_count": True,            # among plans needing changes, fewer changes rank first
    "max_spending_changes": 3,
}

# Flags applied while loading data; changing them forces a reload.
DATA_FLAGS = {"fx_date_field", "fx_allow_inverse", "fx_missing_rate", "fx_round_2dp", "linked_resolution",
              "blank_amount_policy"}

_CACHE: dict = {}


def set_config(**overrides) -> None:
    unknown = set(overrides) - set(CONFIG)
    if unknown:
        raise KeyError(f"unknown CONFIG keys: {sorted(unknown)}")
    reload = any(k in DATA_FLAGS and CONFIG[k] != v for k, v in overrides.items())
    CONFIG.update(overrides)
    data = _CACHE.get("data")
    _CACHE.clear()
    if data is not None and not reload:
        _CACHE["data"] = data


# =====================================================================================
# Data model
# =====================================================================================
@dataclass(frozen=True)
class Profile:
    user_id: str
    home_currency: str
    balance: float
    minimum_balance: float
    priorities: tuple
    protect: tuple
    reduce_ok: tuple
    stop_ok: tuple
    payment_methods: tuple
    max_installment_months: int | None


@dataclass
class Event:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    amount: float | None          # original currency; None when blank
    currency: str
    event_date: date
    settlement_date: date | None
    status: str
    linked_event_id: str
    flexibility: str
    minimum_allowed_amount: float | None
    amount_home: float | None = None
    min_allowed_home: float | None = None
    amount_source: str = "csv"    # csv | image_override | missing
    superseded_by: str = ""

    @property
    def cash_date(self) -> date:
        return self.settlement_date or self.event_date

    @property
    def sign(self) -> int:
        return {"credit": 1, "debit": -1}.get(self.direction, 0)


@dataclass
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: float
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str
    expected: dict | None = None  # filled for sample_requests.csv rows only


@dataclass
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str
    payment_amount: float
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: int | None
    financing_fee: float
    total_payable_amount: float

    def schedule(self) -> list[tuple[date, float]]:
        step = self.payment_frequency_days or 0
        return [(self.first_payment_date + timedelta(days=step * i), self.payment_amount)
                for i in range(self.number_of_payments)]


@dataclass
class Message:
    message_id: str
    user_id: str
    request_id: str
    related_event_id: str
    sent_at: str
    source_type: str
    message_text: str


@dataclass
class Image:
    image_id: str
    user_id: str
    request_id: str
    related_event_id: str
    path: Path


@dataclass
class Data:
    profiles: dict
    events: dict
    events_by_user: dict
    requests: dict
    options_by_request: dict
    messages_by_user: dict
    messages_by_request: dict
    images_by_event: dict
    images_by_request: dict
    fx: dict
    warnings: list = field(default_factory=list)


@dataclass
class Series:
    series_id: str
    user_id: str
    direction: str
    event_type: str
    description: str
    category: str
    events: list
    dom: int
    interval_days: int
    amount_home: float
    flexibility: str
    min_allowed_home: float | None

    @property
    def latest(self) -> Event:
        return self.events[-1]

    @property
    def last_date(self) -> date:
        return self.events[-1].cash_date


@dataclass
class LedgerItem:
    date: date
    amount: float            # signed, home currency (+credit / -debit)
    kind: str                # scheduled | pending | projected | variable | payment
    event_id: str
    series_id: str
    description: str
    category: str
    flexibility: str


# =====================================================================================
# Parsing helpers
# =====================================================================================
def _d(s: str) -> date | None:
    return date.fromisoformat(s) if s else None


def _f(s: str) -> float | None:
    return float(s) if s not in ("", None) else None


def _split(s: str) -> tuple:
    return tuple(t for t in s.split("|") if t) if s else ()


def _read(name: str, dataset_dir: Path) -> list[dict]:
    with open(dataset_dir / f"{name}.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def id_num(identifier: str) -> int:
    tail = identifier.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def format_amount(x: float) -> str:
    if CONFIG["amount_format"] == "int_if_whole_else_2dp" and abs(x - round(x)) < 0.005:
        return str(int(round(x)))
    return f"{x:.2f}"


def round_amount(x: float) -> float:
    mode = CONFIG["rounding_mode"]
    if mode == "floor_2dp":
        return math.floor(x * 100 + 1e-6) / 100
    if mode == "round_2dp":
        return round(x, 2)
    if mode == "floor_int":
        return float(math.floor(x + 1e-9))
    if mode == "round_int":
        return float(round(x))
    raise ValueError(mode)


def is_safe_margin(margin: float) -> bool:
    return margin > 1e-6 if CONFIG["unsafe_if_equal_to_minimum"] else margin >= -1e-6


# =====================================================================================
# Exchange rates
# =====================================================================================
def fx_rate(fx: dict, frm: str, to: str, on: date) -> float:
    if frm == to:
        return 1.0
    direct, inverse = fx.get((frm, to), {}), fx.get((to, frm), {})
    if on in direct:
        return direct[on]
    if CONFIG["fx_allow_inverse"] and on in inverse:
        return 1.0 / inverse[on]
    mode = CONFIG["fx_missing_rate"]
    if mode == "error":
        raise KeyError(f"no {frm}->{to} rate on {on}")
    candidates = [(d, r) for d, r in direct.items()]
    if CONFIG["fx_allow_inverse"]:
        candidates += [(d, 1.0 / r) for d, r in inverse.items()]
    if not candidates:
        raise KeyError(f"no {frm}->{to} rates at all")
    prior = [c for c in candidates if c[0] <= on]
    if mode == "nearest_prior" and prior:
        return max(prior)[1]
    return min(candidates, key=lambda c: (abs((c[0] - on).days), c[0]))[1]


def to_home(fx: dict, amount: float, currency: str, home: str, on: date) -> float:
    value = amount * fx_rate(fx, currency, home, on)
    return round(value, 2) if CONFIG["fx_round_2dp"] else value


# =====================================================================================
# 1. load_all
# =====================================================================================
def load_image_amounts(path: Path = IMAGE_AMOUNTS_PATH) -> dict:
    """{event_id: (amount, currency_or_None)} from the extraction cache (dict entries or bare numbers)."""
    if not path.exists():
        return {}
    out = {}
    for event_id, value in json.loads(path.read_text(encoding="utf-8")).items():
        if isinstance(value, dict):
            if isinstance(value.get("amount"), (int, float)) and value["amount"] > 0:
                out[event_id] = (float(value["amount"]), (value.get("currency") or "").upper() or None)
        elif isinstance(value, (int, float)):
            out[event_id] = (float(value), None)
    return out


def load_all(dataset_dir: Path = DATASET_DIR, image_amounts_path: Path = IMAGE_AMOUNTS_PATH) -> Data:
    warnings: list[str] = []
    fx: dict = defaultdict(dict)
    for r in _read("exchange_rates", dataset_dir):
        fx[(r["from_currency"], r["to_currency"])][_d(r["rate_date"])] = float(r["rate"])
    known_currencies = {c for pair in fx for c in pair}

    profiles = {
        r["user_id"]: Profile(
            user_id=r["user_id"], home_currency=r["home_currency"],
            balance=float(r["current_available_balance"]), minimum_balance=float(r["minimum_balance_to_keep"]),
            priorities=_split(r["financial_priorities"]), protect=_split(r["expense_categories_to_protect"]),
            reduce_ok=_split(r["expense_categories_user_is_willing_to_reduce"]),
            stop_ok=_split(r["expense_categories_user_is_willing_to_stop"]),
            payment_methods=_split(r["payment_methods_user_will_consider"]),
            max_installment_months=int(float(r["max_installment_months"])) if r["max_installment_months"] else None,
        )
        for r in _read("financial_profiles", dataset_dir)
    }

    image_amounts = load_image_amounts(image_amounts_path)
    events: dict[str, Event] = {}
    for r in _read("financial_events", dataset_dir):
        ev = Event(
            event_id=r["event_id"], user_id=r["user_id"], event_type=r["event_type"], description=r["description"],
            category=r["category"], direction=r["direction"], amount=_f(r["amount"]), currency=r["currency"],
            event_date=_d(r["event_date"]), settlement_date=_d(r["settlement_date"]), status=r["status"],
            linked_event_id=r["linked_event_id"], flexibility=r["flexibility"],
            minimum_allowed_amount=_f(r["minimum_allowed_amount"]),
        )
        if ev.amount is None:
            if ev.event_id in image_amounts:
                amount, currency = image_amounts[ev.event_id]
                ev.amount, ev.amount_source = amount, "image_override"
                if currency and currency != ev.currency:
                    if currency in known_currencies:
                        warnings.append(f"{ev.event_id} image currency {currency} differs from row {ev.currency}; using image")
                        ev.currency = currency
                    else:
                        warnings.append(f"{ev.event_id} image currency {currency} unknown; keeping row {ev.currency}")
            else:
                ev.amount_source = "missing"
                if CONFIG["blank_amount_policy"] == "override_else_error":
                    raise ValueError(f"{ev.event_id} has blank amount and no image override")
                warnings.append(f"{ev.event_id} ({ev.user_id}) blank amount, no image override -> excluded")
        events[ev.event_id] = ev

    for ev in events.values():
        home = profiles[ev.user_id].home_currency
        fx_day = ev.settlement_date if CONFIG["fx_date_field"] == "settlement_date" and ev.settlement_date else ev.event_date
        if ev.amount is not None:
            ev.amount_home = to_home(fx, ev.amount, ev.currency, home, fx_day)
        if ev.minimum_allowed_amount is not None:
            ev.min_allowed_home = to_home(fx, ev.minimum_allowed_amount, ev.currency, home, fx_day)
        if ev.linked_event_id and CONFIG["linked_resolution"] == "child_supersedes_parent":
            parent = events.get(ev.linked_event_id)
            if parent is not None:
                parent.superseded_by = ev.event_id

    events_by_user = defaultdict(list)
    for ev in events.values():
        events_by_user[ev.user_id].append(ev)
    for evs in events_by_user.values():
        evs.sort(key=lambda e: (e.cash_date, id_num(e.event_id)))

    requests: dict[str, Request] = {}
    out_cols = ["amount_safe_to_pay", "affordability_status", "recommended_payment_method", "payment_plan",
                "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation"]
    for name in ("sample_requests", "requests"):
        for r in _read(name, dataset_dir):
            requests[r["request_id"]] = Request(
                request_id=r["request_id"], user_id=r["user_id"], request_date=_d(r["request_date"]),
                request_type=r["request_type"], requested_amount=float(r["requested_amount"]),
                desired_completion_date=_d(r["desired_completion_date"]),
                allows_partial_payment=r["allows_partial_payment"].strip().lower() == "true",
                request_text=r["request_text"],
                expected={c: r[c] for c in out_cols} if name == "sample_requests" else None,
            )

    options = defaultdict(list)
    for r in _read("request_payment_options", dataset_dir):
        options[r["request_id"]].append(PaymentOption(
            payment_option_id=r["payment_option_id"], request_id=r["request_id"], payment_method=r["payment_method"],
            payment_amount=float(r["payment_amount"]), number_of_payments=int(r["number_of_payments"]),
            first_payment_date=_d(r["first_payment_date"]),
            payment_frequency_days=int(float(r["payment_frequency_days"])) if r["payment_frequency_days"] else None,
            financing_fee=float(r["financing_fee"]), total_payable_amount=float(r["total_payable_amount"]),
        ))

    messages_by_user, messages_by_request = defaultdict(list), defaultdict(list)
    for r in _read("messages", dataset_dir):
        m = Message(**r)
        messages_by_user[m.user_id].append(m)
        if m.request_id:
            messages_by_request[m.request_id].append(m)

    images_by_event, images_by_request = {}, defaultdict(list)
    for r in _read("images", dataset_dir):
        img = Image(path=dataset_dir / "media" / "images" / f"{r['image_id']}.png", **r)
        if img.related_event_id:
            images_by_event[img.related_event_id] = img
        if img.request_id:
            images_by_request[img.request_id].append(img)

    return Data(profiles, events, dict(events_by_user), requests, dict(options), dict(messages_by_user),
                dict(messages_by_request), images_by_event, dict(images_by_request), dict(fx), warnings)


def get_data() -> Data:
    if "data" not in _CACHE:
        _CACHE["data"] = load_all()
    return _CACHE["data"]


# =====================================================================================
# 2. build_ledger
# =====================================================================================
def forecast_window(request_date: date, days: int | None = None) -> tuple[date, date]:
    days = CONFIG["horizon_days"] if days is None else days
    start = request_date + timedelta(days=CONFIG["forecast_starts_day_0_or_1"])
    end = request_date + timedelta(days=days if CONFIG["forecast_includes_day_90"] else days - 1)
    return start, end


def _is_possible_duplicate(ev: Event, data: Data) -> bool:
    parent = data.events.get(ev.linked_event_id)
    return (parent is not None and ev.status == "pending" and parent.status == "settled"
            and parent.event_type == ev.event_type and parent.direction == ev.direction
            and parent.amount == ev.amount)


def future_row_role(ev: Event, request_date: date, window_end: date, data: Data) -> tuple[bool, str]:
    """Decide whether a supplied (non-projected) event row is a future cash movement in the window."""
    if ev.direction == "non_cash" or ev.status == "unrealized":
        return False, "non-cash / unrealized value"
    if ev.status in ("failed", "cancelled"):
        return False, ev.status
    if ev.superseded_by and CONFIG["linked_resolution"] == "child_supersedes_parent":
        return False, f"superseded by {ev.superseded_by}"
    if ev.status == "settled" and ev.cash_date <= request_date:
        return False, "historical (already in balance)"
    if ev.cash_date > window_end:
        return False, "beyond forecast window"
    if ev.amount_home is None:
        return False, "blank amount (needs image)"
    if ev.status == "pending":
        if ev.direction == "credit":
            return CONFIG["include_pending_credits"], "pending credit"
        if _is_possible_duplicate(ev, data) and CONFIG["possible_duplicate_pending_debit"] == "exclude":
            return False, f"possible duplicate of {ev.linked_event_id}"
        return CONFIG["include_pending_debits"], "pending debit"
    if ev.status == "scheduled":
        key = "include_scheduled_credits" if ev.direction == "credit" else "include_scheduled_debits"
        return CONFIG[key], f"scheduled {ev.direction}"
    return True, f"{ev.status} future row"


def _explicit_items(user_id: str, request_date: date, start: date, end: date, data: Data) -> list[LedgerItem]:
    items = []
    for ev in data.events_by_user.get(user_id, []):
        include, _ = future_row_role(ev, request_date, end, data)
        if not include:
            continue
        when = ev.cash_date
        if ev.status == "pending" and ev.direction == "debit" and CONFIG["pending_debits_reserved_immediately"]:
            when = request_date
        when = max(when, start)
        items.append(LedgerItem(when, ev.sign * ev.amount_home, ev.status, ev.event_id, "", ev.description,
                                ev.category, ev.flexibility))
    return items


# ---------------------------------------------------------------- recurring series
def _is_irregular_income(ev: Event) -> bool:
    text = ev.description.lower()
    return any(k in text for k in CONFIG["irregular_income_keywords"])


def _series_key(ev: Event) -> tuple:
    if ev.direction == "credit" and CONFIG["income_series_key"] == "category_dom":
        return ("credit", ev.category, ev.cash_date.day)
    return (ev.direction, ev.event_type, ev.description, ev.category)


def _is_series_candidate(ev: Event, window_end: date) -> bool:
    if ev.status not in ("settled", "scheduled") or ev.linked_event_id or ev.cash_date > window_end:
        return False
    if ev.superseded_by and CONFIG["linked_resolution"] == "child_supersedes_parent":
        return False
    if ev.direction == "credit":
        return (CONFIG["recurring_include_income"] and ev.event_type == "income"
                and ev.category in CONFIG["income_projection_categories"]
                and (CONFIG["project_irregular_income"] or not _is_irregular_income(ev)))
    return ev.direction == "debit" and ev.event_type in CONFIG["recurring_expense_event_types"]


def _basis(values: list[float], basis: str) -> float:
    if basis in ("last", "last_occurrence"):
        return values[-1]
    if basis == "max":
        return max(values)
    if basis == "median":
        return statistics.median(values)
    return sum(values) / len(values)


def _series_amount(evs: list[Event]) -> float | None:
    amounts = [e.amount_home for e in evs if e.amount_home is not None]
    if not amounts:
        return None
    if evs[0].direction == "credit":
        mode = CONFIG["salary_projection_amount"]
        n = CONFIG["salary_projection_n"]
        window = amounts if n == "all" else amounts[-int(n):]
        value = _basis(window, {"last_occurrence": "last", "median_of_last_n": "median", "mean_of_last_n": "mean"}[mode])
    else:
        value = _basis(amounts, CONFIG["recurring_amount_basis"])
    return round(value, 2)


def detect_series(user_id: str, request_date: date, data: Data | None = None, days: int | None = None) -> list[Series]:
    data = data or get_data()
    key = ("series", user_id, request_date, days, id(data))
    if key in _CACHE:
        return _CACHE[key]
    _, end = forecast_window(request_date, days)
    excluded = message_excluded_ids(user_id, request_date, data)
    groups = defaultdict(list)
    for ev in data.events_by_user.get(user_id, []):
        if ev.event_id not in excluded and _is_series_candidate(ev, end):
            groups[_series_key(ev)].append(ev)

    series = []
    for gkey, evs in groups.items():
        evs.sort(key=lambda e: (e.cash_date, id_num(e.event_id)))
        credit = evs[0].direction == "credit"
        min_n = CONFIG["recurring_min_occurrences_income" if credit else "recurring_min_occurrences"]
        doms = [e.cash_date.day for e in evs]
        months = {(e.cash_date.year, e.cash_date.month) for e in evs}
        if len(evs) < min_n or max(doms) - min(doms) > CONFIG["recurring_max_dom_spread"]:
            continue
        if CONFIG["recurring_require_one_per_month"] and len(months) != len(evs):
            continue
        history = [e for e in evs if e.cash_date <= request_date]
        future = [e for e in evs if e.cash_date > request_date]
        cutoff = CONFIG["stopped_income_cutoff_days" if credit else "recurring_max_staleness_days"]
        if not future and (not history or (request_date - history[-1].cash_date).days > cutoff):
            continue
        amount = _series_amount(evs)
        if amount is None:
            data.warnings.append(f"series {gkey} for {user_id} has no usable amount")
            continue
        dom = doms[-1] if CONFIG["recurring_day_basis"] == "last" else Counter(doms).most_common(1)[0][0]
        gaps = [(b.cash_date - a.cash_date).days for a, b in zip(evs, evs[1:])]
        latest = evs[-1]
        series.append(Series(
            series_id=f"{user_id}|{'|'.join(map(str, gkey))}", user_id=user_id, direction=latest.direction,
            event_type=latest.event_type, description=latest.description, category=latest.category, events=evs,
            dom=dom, interval_days=int(round(statistics.median(gaps))) if gaps else 30, amount_home=amount,
            flexibility=latest.flexibility, min_allowed_home=latest.min_allowed_home,
        ))
    series.sort(key=lambda s: (s.direction, s.dom, s.description))
    _CACHE[key] = series
    return series


def irregular_flexible_series(user_id: str, request_date: date, data: Data | None = None) -> list[Series]:
    """Flexible (non-fixed) expense groups that are not detected monthly series, keyed by description + category.
    Only groups with a row inside the variable-spending lookback are returned."""
    data = data or get_data()
    key = ("irregular", user_id, request_date, id(data))
    if key in _CACHE:
        return _CACHE[key]
    detected = {e.event_id for s in detect_series(user_id, request_date, data) for e in s.events}
    excluded = message_excluded_ids(user_id, request_date, data)
    lookback = CONFIG["variable_lookback_days"]
    oldest = request_date - timedelta(days=int(lookback)) if lookback != "all_history" else date.min
    groups = defaultdict(list)
    for ev in data.events_by_user.get(user_id, []):
        if (ev.direction == "debit" and ev.event_type in CONFIG["recurring_expense_event_types"] and ev.status == "settled"
                and ev.flexibility != "fixed" and not ev.linked_event_id and not ev.superseded_by
                and ev.event_id not in detected and ev.event_id not in excluded and ev.amount_home is not None
                and ev.cash_date <= request_date):
            groups[(ev.description, ev.category)].append(ev)
    out = []
    for (desc, cat), evs in sorted(groups.items()):
        evs.sort(key=lambda e: (e.cash_date, id_num(e.event_id)))
        latest = evs[-1]
        if latest.cash_date <= oldest:
            continue
        out.append(Series(
            series_id=f"{user_id}|irregular|{desc}|{cat}", user_id=user_id, direction="debit", event_type=latest.event_type,
            description=latest.description, category=cat, events=evs, dom=latest.cash_date.day, interval_days=30,
            amount_home=round(sum(e.amount_home for e in evs) / len(evs), 2), flexibility=latest.flexibility,
            min_allowed_home=latest.min_allowed_home,
        ))
    _CACHE[key] = out
    return out


def _irregular_items(user_id: str, request_date: date, start: date, end: date, data: Data) -> list[LedgerItem]:
    mode = CONFIG["irregular_flexible_projection"]
    if mode == "none":
        return []
    items = []
    for s in irregular_flexible_series(user_id, request_date, data):
        dom = start.day if mode == "monthly_mean_from_start" else s.dom
        y, m = start.year, start.month
        while True:
            d = date(y, m, min(dom, calendar.monthrange(y, m)[1]))
            if d > end:
                break
            if d >= start:
                items.append(LedgerItem(d, -s.amount_home, "projected", s.latest.event_id, s.series_id, s.description,
                                        s.category, s.flexibility))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return items


def _month_dates_after(last: date, dom: int, until: date):
    y, m = last.year, last.month
    while True:
        m += 1
        if m > 12:
            y, m = y + 1, 1
        d = date(y, m, min(dom, calendar.monthrange(y, m)[1]))
        if d > until:
            return
        yield d


def _occurrence_dates(s: Series, until: date):
    if s.direction == "credit" and CONFIG["salary_projection_day"] == "same_interval":
        d = s.last_date + timedelta(days=s.interval_days)
        while d <= until:
            yield d
            d += timedelta(days=s.interval_days)
        return
    yield from _month_dates_after(s.last_date, s.dom, until)


def _projected_items(series: list[Series], explicit: list[LedgerItem], start: date, end: date) -> list[LedgerItem]:
    mode, window = CONFIG["dedupe_projection_against_explicit"], CONFIG["dedupe_window_days"]
    catch_up = CONFIG["project_recurring_from"] == "last_row_date"
    items = []
    for s in series:
        sign = 1 if s.direction == "credit" else -1
        for d in _occurrence_dates(s, end):
            if d < start:
                if not catch_up:
                    continue
                d = start
            if mode == "all" or (mode == "credits_only" and s.direction == "credit"):
                if any(x.category == s.category and x.amount * sign > 0 and abs((x.date - d).days) <= window
                       for x in explicit):
                    continue
            items.append(LedgerItem(d, sign * s.amount_home, "projected", s.latest.event_id, s.series_id,
                                    s.description, s.category, s.flexibility))
    return items


# ---------------------------------------------------------------- variable spending
def _variable_rows(user_id: str, request_date: date, series: list[Series], data: Data) -> list[Event]:
    in_series = {e.event_id for s in series for e in s.events} | message_excluded_ids(user_id, request_date, data)
    if CONFIG["irregular_flexible_projection"] != "none":  # already forecast individually, do not average them again
        in_series |= {e.event_id for s in irregular_flexible_series(user_id, request_date, data) for e in s.events}
    protect = set(data.profiles[user_id].protect)
    scope = CONFIG["variable_spending_categories"]
    rows = []
    for ev in data.events_by_user.get(user_id, []):
        if (ev.direction != "debit" or ev.event_type != "expense" or ev.status != "settled" or ev.linked_event_id
                or ev.superseded_by or ev.event_id in in_series or ev.amount_home is None or ev.cash_date > request_date):
            continue
        if scope == "protected_only" and ev.category not in protect:
            continue
        if scope == "all_except_flexible" and ev.flexibility != "fixed":
            continue
        rows.append(ev)
    return rows


def _variable_window(user_id: str, request_date: date, rows: list[Event], data: Data) -> tuple[date, int, list[Event]]:
    user_events = data.events_by_user.get(user_id, [])
    if CONFIG["variable_window_anchor"] == "last_history_date":
        anchor = max((e.cash_date for e in user_events if e.status == "settled" and e.cash_date <= request_date),
                     default=request_date)
    else:
        anchor = request_date
    lookback = CONFIG["variable_lookback_days"]
    if lookback == "all_history":
        length = (anchor - min(e.cash_date for e in user_events)).days + 1
    else:
        length = int(lookback)
    lo = anchor - timedelta(days=length)
    return anchor, length, [e for e in rows if lo < e.cash_date <= anchor]


def _monthly_rate(evs: list[Event], anchor: date, length: int) -> float:
    total = sum(e.amount_home for e in evs)
    if CONFIG["variable_average_basis"] == "median":
        blocks = max(1, length // 30)
        block_totals = [0.0] * blocks
        for e in evs:
            idx = (anchor - e.cash_date).days // 30
            if idx < blocks:
                block_totals[idx] += e.amount_home
        return statistics.median(block_totals)
    return total * 30 / length


def _variable_items(user_id: str, request_date: date, series: list[Series], start: date, end: date,
                    data: Data) -> list[LedgerItem]:
    mode = CONFIG["variable_spending_mode"]
    if mode == "none":
        return []
    anchor, length, window = _variable_window(user_id, request_date, _variable_rows(user_id, request_date, series, data), data)
    if not window:
        return []
    items = []
    if mode == "description_monthly":
        groups = defaultdict(list)
        for ev in window:
            groups[(ev.description, ev.category)].append(ev)
        for (desc, cat), evs in sorted(groups.items()):
            evs.sort(key=lambda e: e.cash_date)
            amount = _basis([e.amount_home for e in evs], CONFIG["description_amount_basis"])
            dom = evs[-1].cash_date.day
            y, m = start.year, start.month
            while True:
                d = date(y, m, min(dom, calendar.monthrange(y, m)[1]))
                if d > end:
                    break
                if d >= start:
                    items.append(LedgerItem(d, -amount, "variable", evs[-1].event_id, f"variable|{desc}",
                                            f"monthly {desc}", cat, evs[-1].flexibility))
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return items
    if mode == "replay_last_period":
        for ev in window:
            k = 1
            while (d := ev.cash_date + timedelta(days=length * k)) <= end:
                if d >= start:
                    items.append(LedgerItem(d, -ev.amount_home, "variable", ev.event_id, f"variable|{ev.category}",
                                            f"replay {ev.description}", ev.category, ev.flexibility))
                k += 1
        return items

    by_cat = defaultdict(list)
    for ev in window:
        by_cat[ev.category].append(ev)
    applied = CONFIG["variable_applied_as"]
    for cat, evs in sorted(by_cat.items()):
        monthly = _monthly_rate(evs, anchor, length)
        total = sum(e.amount_home for e in evs) or 1.0
        wd_share = defaultdict(float)
        dom_share = defaultdict(float)
        for e in evs:
            wd_share[e.cash_date.weekday()] += e.amount_home / total
            dom_share[e.cash_date.day] += e.amount_home / total
        d = start
        while d <= end:
            dim = calendar.monthrange(d.year, d.month)[1]
            if mode == "daily_average":
                if applied == "even_daily_amount":
                    amt = monthly / 30
                elif applied == "same_weekday_pattern":
                    amt = monthly / 30 * 7 * wd_share[d.weekday()]
                else:
                    amt = monthly * dom_share[d.day]
            else:  # monthly_total_spread
                if applied == "even_daily_amount":
                    amt = monthly / dim
                elif applied == "same_weekday_pattern":
                    same_wd = sum(1 for k in range(1, dim + 1) if date(d.year, d.month, k).weekday() == d.weekday())
                    amt = monthly * wd_share[d.weekday()] / same_wd
                else:
                    amt = monthly * dom_share[d.day]
            if amt:
                items.append(LedgerItem(d, -amt, "variable", "", f"variable|{cat}", f"variable {cat}", cat, "fixed"))
            d += timedelta(days=1)
    return items


def _message_rules():
    import message_rules  # local import: message_rules receives this module as an argument, never imports it
    return message_rules


def message_excluded_ids(user_id: str, request_date: date, data: Data) -> set[str]:
    if not CONFIG["apply_message_effects"]:
        return set()
    return _message_rules().excluded_event_ids(user_id, request_date, data, sys.modules[__name__])


def _order_key(item: LedgerItem) -> tuple:
    credit_first = CONFIG["salary_applied_before_expenses_same_day"]
    is_credit = item.amount > 0
    return (item.date, 0 if is_credit == credit_first else 1)


def build_ledger(user_id: str, request_date: date, days: int | None = None, data: Data | None = None) -> list[LedgerItem]:
    data = data or get_data()
    key = ("ledger", user_id, request_date, days, id(data))
    if key not in _CACHE:
        start, end = forecast_window(request_date, days)
        explicit = _explicit_items(user_id, request_date, start, end, data)
        series = detect_series(user_id, request_date, data, days)
        items = explicit + _projected_items(series, explicit, start, end) + \
            _irregular_items(user_id, request_date, start, end, data) + \
            _variable_items(user_id, request_date, series, start, end, data)
        if CONFIG["apply_message_effects"]:
            # applied after linked_event_id resolution (explicit rows above already respect superseded_by)
            items = _message_rules().apply_effects(items, user_id, request_date, start, end, data, sys.modules[__name__])
        items.sort(key=_order_key)
        _CACHE[key] = items
    return list(_CACHE[key])


# =====================================================================================
# 3. simulate
# =====================================================================================
def parse_spending_changes(changes) -> list[tuple]:
    if not changes or changes == "none":
        return []
    if isinstance(changes, str):
        changes = changes.split("|")
    parsed = []
    for c in changes:
        if isinstance(c, tuple):
            parsed.append(c)
            continue
        parts = c.split(":")
        parsed.append(("stop", parts[1]) if parts[0] == "stop" else ("reduce_to", parts[1], float(parts[2])))
    return parsed


def series_for_event(user_id: str, request_date: date, event_id: str, data: Data | None = None) -> Series | None:
    for s in detect_series(user_id, request_date, data) + irregular_flexible_series(user_id, request_date, data):
        ids = [s.latest.event_id] if CONFIG["spending_change_event_ref"] == "latest_occurrence" else [e.event_id for e in s.events]
        if event_id in ids:
            return s
    return None


def default_reduce_amount(series: Series) -> float:
    return series.min_allowed_home if CONFIG["reduce_to_uses_minimum_cut"] and series.min_allowed_home is not None else 0.0


def apply_spending_changes(ledger: list[LedgerItem], changes, user_id: str, request_date: date,
                           data: Data | None = None) -> list[LedgerItem]:
    out = list(ledger)
    for change in parse_spending_changes(changes):
        s = series_for_event(user_id, request_date, change[1], data)
        if s is None:
            (data or get_data()).warnings.append(f"spending change {change} matches no projected series for {user_id}")
            continue
        if change[0] == "stop":
            out = [i for i in out if i.series_id != s.series_id]
        else:
            new = -abs(change[2])
            out = [LedgerItem(i.date, max(i.amount, new), i.kind, i.event_id, i.series_id, i.description + " (reduced)",
                              i.category, i.flexibility) if i.series_id == s.series_id else i for i in out]
    return out


def simulate(user_id: str, request_date: date, extra_payments=(), spending_changes=(), days: int | None = None,
             data: Data | None = None):
    """Walk day by day. Returns (is_safe, min_balance_hit, daily_balances[(date, end_of_day_balance)])."""
    data = data or get_data()
    profile = data.profiles[user_id]
    ledger = apply_spending_changes(build_ledger(user_id, request_date, days, data), spending_changes, user_id,
                                    request_date, data)
    payments = [LedgerItem(d, -float(a), "payment", "", "", "requested payment", "request", "fixed")
                for d, a in extra_payments]
    by_day = defaultdict(list)
    for item in sorted(ledger + payments, key=_order_key):
        by_day[item.date].append(item)

    _, end = forecast_window(request_date, days)
    if payments:
        end = max(end, max(p.date for p in payments))
    each = CONFIG["min_balance_checked_after_payment"]
    balance = profile.balance
    min_hit = balance if CONFIG["check_opening_balance"] else math.inf
    daily = []
    day = request_date
    while day <= end:
        for item in by_day.get(day, []):
            balance += item.amount
            if each:
                min_hit = min(min_hit, balance)
        min_hit = min(min_hit, balance)
        daily.append((day, round(balance, 2)))
        day += timedelta(days=1)

    return is_safe_margin(min_hit - profile.minimum_balance), round(min_hit, 2), daily


# =====================================================================================
# Fast path: one no-payment walk gives every single-payment answer
# =====================================================================================
def day_profile(user_id: str, request_date: date, data: Data | None = None) -> list[tuple]:
    """Per day: (date, pre_min, post_base, all_min). A payment P on day d is safe iff every earlier day's
    all_min, the day's pre_min and the opening balance clear the minimum, and min(post_base[d], all_min of later
    days) - P clears it. Mirrors simulate(): payments sort after same-day ledger debits."""
    data = data or get_data()
    key = ("profile", user_id, request_date, id(data))
    if key in _CACHE:
        return _CACHE[key]
    by_day = defaultdict(list)
    for item in build_ledger(user_id, request_date, data=data):
        by_day[item.date].append(item)
    _, end = forecast_window(request_date)
    each = CONFIG["min_balance_checked_after_payment"]
    credit_first = CONFIG["salary_applied_before_expenses_same_day"]
    balance = data.profiles[user_id].balance
    rows = []
    day = request_date
    while day <= end:
        items = by_day.get(day, [])
        credits = [i.amount for i in items if i.amount > 0]
        debits = [i.amount for i in items if i.amount <= 0]
        pre = math.inf
        if credit_first:
            for amt in credits + debits:
                balance += amt
                if each:
                    pre = min(pre, balance)
            post = balance
        else:
            for amt in debits:
                balance += amt
                if each:
                    pre = min(pre, balance)
            post = balance
            for amt in credits:
                balance += amt
            post = min(post, balance) if each else balance
        rows.append((day, pre, post, min(pre, post)))
        day += timedelta(days=1)
    _CACHE[key] = rows
    return rows


def _opening_ok(user_id: str, data: Data) -> bool:
    p = data.profiles[user_id]
    return not CONFIG["check_opening_balance"] or is_safe_margin(p.balance - p.minimum_balance)


def safe_margin_today(user_id: str, request_date: date, data: Data | None = None) -> float:
    """Uncapped largest single payment on request_date (before rounding); -inf when nothing is safe."""
    data = data or get_data()
    rows = day_profile(user_id, request_date, data)
    minimum = data.profiles[user_id].minimum_balance
    if not _opening_ok(user_id, data) or not is_safe_margin(rows[0][1] - minimum):
        return -math.inf
    later = min((r[3] for r in rows[1:]), default=math.inf)
    return min(rows[0][2], later) - minimum


def _round_safe(margin: float) -> float:
    mode = CONFIG["rounding_mode"]
    if mode.startswith("floor"):
        step = 0.01 if mode == "floor_2dp" else 1.0
        candidate = round_amount(margin + 1e-7)
        while candidate > 0 and not is_safe_margin(margin - candidate):
            candidate = round(candidate - step, 2)
        return max(0.0, candidate)
    return max(0.0, round_amount(margin))


# =====================================================================================
# 4. max_safe_today / 5. earliest_full_date
# =====================================================================================
def max_safe_today(user_id: str, request_date: date, requested_amount: float, data: Data | None = None) -> float:
    if CONFIG["use_fast_path"]:
        margin = safe_margin_today(user_id, request_date, data)
        if is_safe_margin(margin - requested_amount):
            return requested_amount
        if not is_safe_margin(margin):
            return 0.0
        return min(_round_safe(margin), requested_amount)
    return max_safe_today_search(user_id, request_date, requested_amount, data)


def max_safe_today_search(user_id: str, request_date: date, requested_amount: float, data: Data | None = None) -> float:
    def ok(amount: float) -> bool:
        return simulate(user_id, request_date, [(request_date, amount)], data=data)[0]

    if ok(requested_amount):
        return requested_amount
    if not ok(0.0):
        return 0.0
    lo, hi = 0.0, requested_amount
    precision = CONFIG["binary_search_precision"]
    while hi - lo > precision:
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    if CONFIG["rounding_mode"].startswith("floor"):
        step = 0.01 if CONFIG["rounding_mode"] == "floor_2dp" else 1.0
        candidate = round_amount(lo + 2 * precision)
        while candidate > 0 and not ok(candidate):
            candidate = round(candidate - step, 2)
        return max(0.0, min(candidate, requested_amount))
    return max(0.0, min(round_amount(lo), requested_amount))


def earliest_full_date(user_id: str, request_date: date, requested_amount: float, data: Data | None = None) -> date | None:
    if CONFIG["use_fast_path"] and CONFIG["earliest_date_window_anchor"] == "request_date":
        data = data or get_data()
        rows = day_profile(user_id, request_date, data)
        minimum = data.profiles[user_id].minimum_balance
        suffix = [math.inf] * (len(rows) + 1)
        for i in range(len(rows) - 1, -1, -1):
            suffix[i] = min(rows[i][3], suffix[i + 1])
        last_offset = min(len(rows) - 1, CONFIG["horizon_days"] if CONFIG["forecast_includes_day_90"] else CONFIG["horizon_days"] - 1)
        prefix_ok = _opening_ok(user_id, data)
        for i in range(last_offset + 1):
            if not prefix_ok:
                return None
            day, pre, post, all_min = rows[i]
            if is_safe_margin(pre - minimum) and is_safe_margin(min(post, suffix[i + 1]) - minimum - requested_amount):
                return day
            prefix_ok = is_safe_margin(all_min - minimum)
        return None
    return earliest_full_date_loop(user_id, request_date, requested_amount, data)


def earliest_full_date_loop(user_id: str, request_date: date, requested_amount: float, data: Data | None = None) -> date | None:
    horizon = CONFIG["horizon_days"]
    last_offset = horizon if CONFIG["forecast_includes_day_90"] else horizon - 1
    for offset in range(last_offset + 1):
        pay_day = request_date + timedelta(days=offset)
        days = horizon + offset if CONFIG["earliest_date_window_anchor"] == "payment_date" else None
        if simulate(user_id, request_date, [(pay_day, requested_amount)], days=days, data=data)[0]:
            return pay_day
    return None


# =====================================================================================
# Readable ledger printout
# =====================================================================================
def print_ledger(request: Request, data: Data | None = None) -> None:
    data = data or get_data()
    p = data.profiles[request.user_id]
    rd, cur = request.request_date, p.home_currency
    start, end = forecast_window(rd)
    print("=" * 118)
    print(f"{request.user_id} / {request.request_id}  request_date={rd}  window={start}..{end}  "
          f"balance={cur} {p.balance:,.2f}  minimum={cur} {p.minimum_balance:,.2f}  requested={cur} {request.requested_amount:,.2f}")
    print(f"  protect={'|'.join(p.protect)}  reduce_ok={'|'.join(p.reduce_ok) or '-'}  stop_ok={'|'.join(p.stop_ok) or '-'}  "
          f"methods={'|'.join(p.payment_methods)}  max_inst_months={p.max_installment_months}")

    print("  -- recurring series detected --")
    for s in detect_series(request.user_id, rd, data):
        print(f"     {s.direction:6} dom={s.dom:<2} {cur} {s.amount_home:>14,.2f}  n={len(s.events)} last={s.last_date} "
              f"latest={s.latest.event_id:<11} {s.description} [{s.category}/{s.flexibility}]")

    print("  -- supplied rows touching the forecast (non-historical, linked, or blank) --")
    for ev in data.events_by_user.get(request.user_id, []):
        include, reason = future_row_role(ev, rd, end, data)
        if reason == "historical (already in balance)" and not ev.linked_event_id and ev.amount_source == "csv":
            continue
        amt = f"{ev.amount:,.2f} {ev.currency}" if ev.amount is not None else "BLANK"
        src = " [image]" if ev.amount_source == "image_override" else ""
        print(f"     {'IN ' if include else 'OUT'} {ev.event_id:<11} {ev.cash_date} {ev.status:<10} {ev.direction:<8} "
              f"{amt:>20}{src}  {ev.description} -> {reason}{'  link=' + ev.linked_event_id if ev.linked_event_id else ''}")

    print("  -- ledger (day walk, no payment, no spending changes; variable spend summed per day) --")
    print(f"     {'date':<10} {'amount':>15} {'balance':>16}  {'kind':<9} {'event':<11} description")
    balance = p.balance
    low = (balance, rd)
    variable_by_day = defaultdict(float)
    for item in build_ledger(request.user_id, rd, data=data):
        if item.kind == "variable":
            variable_by_day[item.date] += item.amount
    for item in build_ledger(request.user_id, rd, data=data):
        if item.kind == "variable":
            continue
        balance += item.amount
        print(f"     {item.date} {item.amount:>15,.2f} {balance:>16,.2f}  {item.kind:<9} {item.event_id:<11} "
              f"{item.description} [{item.category}/{item.flexibility}]")
    total_var = sum(variable_by_day.values())
    if variable_by_day:
        print(f"     (+ variable spending {cur} {total_var:,.2f} over {len(variable_by_day)} days, not shown per line)")
    for day, _, post, all_min in day_profile(request.user_id, rd, data):
        low = min(low, (all_min, day))
    safe = max_safe_today(request.user_id, rd, request.requested_amount, data)
    earliest = earliest_full_date(request.user_id, rd, request.requested_amount, data)
    margin = safe_margin_today(request.user_id, rd, data)
    print(f"  lowest checkpoint {cur} {low[0]:,.2f} on {low[1]}  (uncapped margin today {margin:,.2f})")
    print(f"  ENGINE  max_safe_today={format_amount(safe)}  earliest_full_date={earliest or ''}")
    if request.expected:
        print(f"  SAMPLE  amount_safe_to_pay={request.expected['amount_safe_to_pay']}  "
              f"earliest_date_for_full_payment={request.expected['earliest_date_for_full_payment']}  "
              f"status={request.expected['affordability_status']}  changes={request.expected['spending_changes_needed']}")


def main(argv: list[str]) -> None:
    data = get_data()
    targets = argv or [r.request_id for r in data.requests.values() if r.expected][:3]
    by_user = {r.user_id: r for r in data.requests.values()}
    for t in targets:
        print_ledger(data.requests[t] if t in data.requests else by_user[t], data)
    if data.warnings:
        print("\nwarnings:")
        for w in sorted(set(data.warnings)):
            print("  -", w)


if __name__ == "__main__":
    main(sys.argv[1:])
