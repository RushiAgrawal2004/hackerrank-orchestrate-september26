"""Hard validator for output.csv.

    python code/validate.py                 # validates <repo root>/output.csv against dataset/requests.csv
    python code/validate.py path/to/file.csv

Prints PASS or FAIL with the offending request_ids per check. Exit code 1 on FAIL.
"""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
ROOT = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))
import engine  # noqa: E402

COLUMNS = ["request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method", "payment_plan",
           "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation"]
STATUSES = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
METHODS = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AMOUNT_RE = re.compile(r"^\d+(?:\.\d{1,2})?$")
EPS = 0.005


def parse_date(s: str) -> date:
    if not DATE_RE.match(s):
        raise ValueError(s)
    return date.fromisoformat(s)


def parse_plan(s: str) -> list[tuple[date, float]]:
    if s == "none":
        return []
    out = []
    for part in s.split("|"):
        d, sep, a = part.partition(":")
        if not sep or not AMOUNT_RE.match(a):
            raise ValueError(part)
        out.append((parse_date(d), float(a)))
    return out


def validate(path: Path) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = defaultdict(list)
    data = engine.get_data()
    with open(engine.DATASET_DIR / "requests.csv", newline="", encoding="utf-8") as fh:
        expected_ids = [r["request_id"] for r in csv.DictReader(fh)]
    if not path.exists():
        errors["file_missing"].append(str(path))
        return errors
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        rows = list(reader)
    if header != COLUMNS:
        errors["column_names_or_order"].append(f"got {header}")
        return errors
    if len(rows) != len(expected_ids):
        errors["row_count"].append(f"{len(rows)} rows, expected {len(expected_ids)}")
    records = [dict(zip(COLUMNS, r)) for r in rows]
    ids = [r["request_id"] for r in records]
    for rid in sorted({i for i in ids if ids.count(i) > 1}):
        errors["duplicate_request_id"].append(rid)
    for rid in sorted(set(expected_ids) - set(ids), key=engine.id_num):
        errors["missing_request_id"].append(rid)
    for rid in sorted(set(ids) - set(expected_ids), key=engine.id_num):
        errors["extra_request_id"].append(rid)

    for rec in records:
        rid = rec["request_id"]
        req = data.requests.get(rid)
        if req is None or len(rec) != len(COLUMNS):
            continue
        status, method = rec["affordability_status"], rec["recommended_payment_method"]
        if status not in STATUSES:
            errors["illegal_affordability_status"].append(rid)
        if method not in METHODS:
            errors["illegal_payment_method"].append(rid)

        safe = None
        if not AMOUNT_RE.match(rec["amount_safe_to_pay"]):
            errors["amount_format"].append(rid)
        else:
            safe = float(rec["amount_safe_to_pay"])
            if not (-EPS <= safe <= req.requested_amount + EPS):
                errors["amount_outside_0_requested"].append(rid)

        earliest = None
        if rec["earliest_date_for_full_payment"]:
            try:
                earliest = parse_date(rec["earliest_date_for_full_payment"])
            except ValueError:
                errors["earliest_date_format"].append(rid)
        if status == "affordable_now" and earliest != req.request_date:
            errors["affordable_now_earliest_not_request_date"].append(rid)

        try:
            plan = parse_plan(rec["payment_plan"])
        except ValueError:
            errors["payment_plan_format"].append(rid)
            plan = None
        if plan is not None:
            if any(b[0] <= a[0] for a, b in zip(plan, plan[1:])):
                errors["payment_plan_not_chronological"].append(rid)
            if plan and plan[0][0] < req.request_date:
                errors["payment_before_request_date"].append(rid)
            if method == "not_recommended" and plan:
                errors["not_recommended_with_plan"].append(rid)
            if method != "not_recommended" and not plan:
                errors["missing_payment_plan"].append(rid)
            if (status == "not_affordable") != (method == "not_recommended"):
                errors["status_method_mismatch"].append(rid)
            if method == "full_payment" and (len(plan) != 1 or abs(plan[0][1] - req.requested_amount) > EPS):
                errors["full_payment_plan_invalid"].append(rid)
            if method == "wait" and (len(plan) != 1 or abs(plan[0][1] - req.requested_amount) > EPS
                                     or plan[0][0] != earliest or status != "affordable_later"):
                errors["wait_plan_invalid"].append(rid)
            if method == "partial_payment":
                ok = (len(plan) == 2 and abs(sum(a for _, a in plan) - req.requested_amount) <= EPS
                      and plan[0][0] == req.request_date and safe is not None and abs(plan[0][1] - safe) <= EPS
                      and plan[1][0] == earliest and status == "affordable_with_plan" and req.allows_partial_payment
                      and safe is not None and 0 < safe < req.requested_amount and earliest is not None
                      and earliest <= req.desired_completion_date)
                if not ok:
                    errors["partial_payment_invalid"].append(rid)
            if method == "installments":
                schedules = [[(d, round(a, 2)) for d, a in o.schedule()] for o in data.options_by_request.get(rid, [])
                             if o.payment_method == "installments"]
                mine = [(d, round(a, 2)) for d, a in plan]
                if not any(len(s) == len(mine) and all(d1 == d2 and abs(a1 - a2) <= EPS for (d1, a1), (d2, a2) in zip(s, mine))
                           for s in schedules):
                    errors["installments_not_matching_option"].append(rid)

        changes = rec["spending_changes_needed"]
        if changes != "none":
            parts = changes.split("|")
            if len(parts) > 3:
                errors["spending_changes_over_3"].append(rid)
            seen: dict[str, str] = {}
            for part in parts:
                bits = part.split(":")
                kind = bits[0]
                ev = data.events.get(bits[1]) if len(bits) > 1 else None
                if kind not in ("stop", "reduce_to") or (kind == "stop" and len(bits) != 2) or \
                        (kind == "reduce_to" and (len(bits) != 3 or not AMOUNT_RE.match(bits[2]))):
                    errors["spending_change_format"].append(rid)
                    continue
                if ev is None or ev.user_id != req.user_id:
                    errors["spending_change_unknown_event"].append(rid)
                    continue
                if bits[1] in seen:
                    errors["same_event_changed_twice"].append(rid)
                seen[bits[1]] = kind
                if ev.flexibility == "fixed":
                    errors["spending_change_non_flexible"].append(rid)
                elif kind == "stop" and ev.flexibility not in ("stoppable", "reducible_or_stoppable"):
                    errors["stop_on_non_stoppable"].append(rid)
                elif kind == "reduce_to":
                    if ev.flexibility not in ("reducible", "reducible_or_stoppable"):
                        errors["reduce_on_non_reducible"].append(rid)
                    elif ev.min_allowed_home is not None and float(bits[2]) < ev.min_allowed_home - EPS:
                        errors["reduce_below_minimum_allowed"].append(rid)

        if not rec["decision_explanation"].strip():
            errors["empty_explanation"].append(rid)
    return errors


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "output.csv"
    errors = validate(path)
    if not errors:
        print(f"PASS  {path}")
        return
    print(f"FAIL  {path}")
    for check, ids in errors.items():
        print(f"  {check}: {len(ids)} -> {', '.join(ids[:40])}{' ...' if len(ids) > 40 else ''}")
    sys.exit(1)


if __name__ == "__main__":
    main()
