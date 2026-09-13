"""Shared fixtures: import path, CONFIG isolation, synthetic data builders. No network, no API."""
from __future__ import annotations

import copy
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import pytest

CODE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_DIR))

import engine as E  # noqa: E402
import message_rules as MR  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_config():
    """Every test starts from the engine defaults with empty derived caches, and leaves CONFIG untouched."""
    saved = copy.deepcopy(E.CONFIG)
    E.set_config()          # clears derived caches (ledgers, series), keeps the loaded dataset
    MR._EFFECTS.clear()
    yield
    E.set_config(**saved)
    MR._EFFECTS.clear()


@pytest.fixture(scope="session")
def real_data():
    return E.get_data()


def profile(user_id="user_t", currency="EUR", balance=1000.0, minimum=100.0, methods=("full_payment",),
            max_months=None, protect=("rent",), reduce_ok=(), stop_ok=()):
    return E.Profile(user_id, currency, balance, minimum, ("emergency_savings",), tuple(protect), tuple(reduce_ok),
                     tuple(stop_ok), tuple(methods), max_months)


def event(event_id, event_type, description, category, direction, amount, event_date, settlement_date=None,
          status="settled", linked="", flexibility="fixed", min_allowed=None, user_id="user_t", currency="EUR"):
    ev = E.Event(event_id, user_id, event_type, description, category, direction, amount, currency, event_date,
                 settlement_date or event_date, status, linked, flexibility, min_allowed)
    ev.amount_home = amount
    ev.min_allowed_home = min_allowed
    return ev


def build_data(profiles, events=(), requests=(), options=(), messages=(), fx=None):
    by_id = {e.event_id: e for e in events}
    for e in events:  # mirror load_all(): a child supersedes its parent
        if e.linked_event_id and e.linked_event_id in by_id:
            by_id[e.linked_event_id].superseded_by = e.event_id
    by_user = defaultdict(list)
    for e in events:
        by_user[e.user_id].append(e)
    for evs in by_user.values():
        evs.sort(key=lambda e: (e.cash_date, E.id_num(e.event_id)))
    opts = defaultdict(list)
    for o in options:
        opts[o.request_id].append(o)
    msgs = defaultdict(list)
    for m in messages:
        msgs[m.user_id].append(m)
    return E.Data(profiles={p.user_id: p for p in profiles}, events=by_id, events_by_user=dict(by_user),
                  requests={r.request_id: r for r in requests}, options_by_request=dict(opts),
                  messages_by_user=dict(msgs), messages_by_request={}, images_by_event={}, images_by_request={},
                  fx=fx or {})


def d(y, m, day):
    return date(y, m, day)
