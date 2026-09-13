"""Score engine predictions against dataset/sample_requests.csv.

    python code/evaluate.py
    python code/evaluate.py --set rounding_mode=\"round_2dp\" --set variable_spending_mode=\"daily_average\"

Phase 1 prediction logic is deliberately naive:
    max_safe_today >= requested_amount -> affordable_now / full_payment
    otherwise                          -> not_affordable / not_recommended
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine  # noqa: E402

COLUMNS = ["amount_safe_to_pay", "affordability_status", "recommended_payment_method", "payment_plan",
           "earliest_date_for_full_payment", "spending_changes_needed"]
AMOUNT_TOL_ABS = 1.0    # tolerance view for amount_safe_to_pay: within max(1 unit, 1% of expected)
AMOUNT_TOL_REL = 0.01
EPS = 0.005


# ---------------------------------------------------------------- prediction
def predict(req: engine.Request, data: engine.Data) -> dict:
    import planner
    return planner.recommend(req, data)


def predict_baseline(req: engine.Request, data: engine.Data) -> dict:
    """Phase 1 dummy logic, kept for before/after comparisons."""
    safe = engine.max_safe_today(req.user_id, req.request_date, req.requested_amount, data)
    earliest = engine.earliest_full_date(req.user_id, req.request_date, req.requested_amount, data)
    fmt = engine.format_amount
    if safe >= req.requested_amount - 1e-9:
        return {
            "amount_safe_to_pay": fmt(safe), "affordability_status": "affordable_now",
            "recommended_payment_method": "full_payment",
            "payment_plan": f"{req.request_date}:{fmt(req.requested_amount)}",
            "earliest_date_for_full_payment": req.request_date.isoformat(), "spending_changes_needed": "none",
            "decision_explanation": "baseline",
        }
    return {
        "amount_safe_to_pay": fmt(safe), "affordability_status": "not_affordable",
        "recommended_payment_method": "not_recommended", "payment_plan": "none",
        "earliest_date_for_full_payment": earliest.isoformat() if earliest else "",
        "spending_changes_needed": "none", "decision_explanation": "baseline",
    }


# ---------------------------------------------------------------- comparison
def _float(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_plan(s: str) -> list[tuple[str, float]]:
    if not s or s.strip() == "none":
        return []
    return [(p.split(":")[0], float(p.split(":")[1])) for p in s.split("|")]


def parse_changes(s: str) -> list[tuple]:
    if not s or s.strip() == "none":
        return []
    out = []
    for part in s.split("|"):
        bits = part.split(":")
        out.append((bits[0], bits[1], float(bits[2]) if len(bits) > 2 else None))
    return sorted(out, key=lambda t: (t[0], t[1]))


def same_amount(mine: str, expected: str) -> bool:
    a, b = _float(mine), _float(expected)
    return a is not None and b is not None and abs(a - b) <= EPS


def near_amount(mine: str, expected: str) -> bool:
    a, b = _float(mine), _float(expected)
    return a is not None and b is not None and abs(a - b) <= max(AMOUNT_TOL_ABS, AMOUNT_TOL_REL * abs(b))


def same_plan(mine: str, expected: str) -> bool:
    try:
        a, b = parse_plan(mine), parse_plan(expected)
    except (IndexError, ValueError):
        return False
    return len(a) == len(b) and all(da == db and abs(xa - xb) <= EPS for (da, xa), (db, xb) in zip(a, b))


def same_changes(mine: str, expected: str) -> bool:
    try:
        a, b = parse_changes(mine), parse_changes(expected)
    except (IndexError, ValueError):
        return False
    return len(a) == len(b) and all(
        ka == kb and ea == eb and (xa is None and xb is None or xa is not None and xb is not None and abs(xa - xb) <= EPS)
        for (ka, ea, xa), (kb, eb, xb) in zip(a, b))


EXACT = {
    "amount_safe_to_pay": same_amount,
    "affordability_status": lambda a, b: a.strip() == b.strip(),
    "recommended_payment_method": lambda a, b: a.strip() == b.strip(),
    "payment_plan": same_plan,
    "earliest_date_for_full_payment": lambda a, b: a.strip() == b.strip(),
    "spending_changes_needed": same_changes,
}


# ---------------------------------------------------------------- report
def _parse_overrides(pairs: list[str]) -> dict:
    overrides = {}
    for pair in pairs:
        key, _, raw = pair.partition("=")
        try:
            overrides[key] = json.loads(raw)
        except json.JSONDecodeError:
            overrides[key] = raw
    return overrides


def score_rows(data: engine.Data | None = None) -> list[dict]:
    """Per sample row: predictions, expected values, exact-match flags per column, amount tolerance flag."""
    data = data or engine.get_data()
    samples = sorted((r for r in data.requests.values() if r.expected), key=lambda r: engine.id_num(r.request_id))
    rows = []
    for req in samples:
        mine = predict(req, data)
        rows.append({
            "request_id": req.request_id, "mine": mine, "expected": req.expected,
            "ok": {col: EXACT[col](mine[col], req.expected[col]) for col in COLUMNS},
            "near": near_amount(mine["amount_safe_to_pay"], req.expected["amount_safe_to_pay"]),
        })
    return rows


def column_table(rows: list[dict]) -> dict:
    n = len(rows)
    table = {col: sum(r["ok"][col] for r in rows) for col in COLUMNS}
    table["amount_safe_to_pay (tolerance)"] = sum(r["near"] for r in rows)
    table["row_exact"] = sum(all(r["ok"].values()) for r in rows)
    table["n"] = n
    return table


def evaluate(show_rows: bool = True) -> dict:
    data = engine.get_data()
    rows = score_rows(data)
    failures = defaultdict(list)         # column -> [(request_id, mine, expected)]
    row_fail_cols = {}
    near_hits = sum(r["near"] for r in rows)
    for r in rows:
        bad = [col for col in COLUMNS if not r["ok"][col]]
        for col in bad:
            failures[col].append((r["request_id"], r["mine"][col], r["expected"][col]))
        row_fail_cols[r["request_id"]] = bad

    n = len(rows)
    print(f"== Evaluation on {n} sample requests ==")
    print("column accuracy (exact):")
    for col in COLUMNS:
        ok = n - len(failures[col])
        print(f"  {col:<34} {ok:>3}/{n}  {100 * ok / n:5.1f}%")
    print(f"  {'amount_safe_to_pay (tolerance)':<34} {near_hits:>3}/{n}  {100 * near_hits / n:5.1f}%"
          f"   [within max({AMOUNT_TOL_ABS:g}, {AMOUNT_TOL_REL:.0%} of expected)]")
    rows_ok = sum(1 for bad in row_fail_cols.values() if not bad)
    print(f"row exact match (6 structured columns): {rows_ok}/{n}  {100 * rows_ok / n:.1f}%")
    print("  (decision_explanation is not scored here)")

    if show_rows:
        print("\n== failures grouped by column (biggest cause first) ==")
        for col, items in sorted(failures.items(), key=lambda kv: (-len(kv[1]), COLUMNS.index(kv[0]))):
            print(f"\n--- {col}: {len(items)} failing ---")
            print(f"    {'request_id':<12} {'mine':<48} expected")
            for rid, mine, exp in items:
                extra = ""
                if col == "amount_safe_to_pay" and _float(mine) is not None and _float(exp) is not None:
                    extra = f"   (diff {_float(mine) - _float(exp):+,.2f})"
                print(f"    {rid:<12} {mine or '<empty>':<48} {exp or '<empty>'}{extra}")

        print("\n== failing columns per row ==")
        for rid, bad in row_fail_cols.items():
            if bad:
                print(f"    {rid:<12} {', '.join(bad)}")

    if data.warnings:
        print(f"\nengine warnings ({len(set(data.warnings))} unique):")
        for w in sorted(set(data.warnings)):
            print("  -", w)
    return {"rows_ok": rows_ok, "n": n, "failures": {c: len(v) for c, v in failures.items()}, "near": near_hits}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="JSON file with 'fitted_flags' (e.g. code/best_config.json) applied before --set")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=JSON", help="override a CONFIG flag")
    ap.add_argument("--quiet", action="store_true", help="only print the summary")
    args = ap.parse_args()
    if args.config:
        blob = json.loads(Path(args.config).read_text(encoding="utf-8"))
        flags = blob.get("fitted_flags") or blob.get("config") or blob
        engine.set_config(**{k: v for k, v in flags.items() if k in engine.CONFIG})
        print(f"CONFIG loaded from {args.config}")
    overrides = _parse_overrides(args.set)
    if overrides:
        engine.set_config(**overrides)
        print(f"CONFIG overrides: {overrides}")
    evaluate(show_rows=not args.quiet)


if __name__ == "__main__":
    main()
