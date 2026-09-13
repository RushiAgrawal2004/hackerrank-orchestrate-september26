"""Fit engine CONFIG flags against dataset/sample_requests.csv, with an overfitting guard.

    python code/fit_flags.py

1. Coordinate ascent from the current CONFIG: for each flag try every value, keep the best. Repeat passes until
   no flag is adopted.
2. Full grid search over the 6 most impactful flags to catch interactions.

Guard: a change is adopted only if it raises the weighted score AND fixes at least MIN_NET_ROWS more rows than it
breaks. Otherwise the default is kept and the change is reported as "insufficient evidence".
Writes code/best_config.json. Never uses requests.csv labels (there are none) and never hardcodes request ids.
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine  # noqa: E402
import evaluate  # noqa: E402

OUT_PATH = Path(__file__).resolve().parent / "best_config.json"
WEIGHTS = {
    "amount_safe_to_pay": 0.30,
    "affordability_status": 0.25,
    "earliest_date_for_full_payment": 0.20,
    "recommended_payment_method": 0.10,   # method + plan share 20%
    "payment_plan": 0.10,
    "spending_changes_needed": 0.05,
}
MIN_NET_ROWS = 2        # "changes the score by 1 row or less" -> not adopted
MAX_PASSES = 5
GRID_TOP_K = 6
MAX_GRID = 6000

SEARCH_SPACE = {
    # variable spending
    "variable_spending_mode": ["none", "daily_average", "monthly_total_spread", "replay_last_period"],
    "variable_lookback_days": [30, 60, 90, "all_history"],
    "variable_spending_categories": ["protected_only", "all", "all_except_flexible"],
    "variable_average_basis": ["mean", "median"],
    "variable_applied_as": ["even_daily_amount", "same_weekday_pattern", "same_day_of_month_pattern"],
    "variable_window_anchor": ["request_date", "last_history_date"],
    "irregular_flexible_projection": ["none", "monthly_mean", "monthly_mean_from_start"],
    # recurring debits
    "project_recurring_from": ["request_date", "last_row_date"],
    "recurring_amount_basis": ["last", "mean", "max"],
    "recurring_min_occurrences": [2, 3, 5],
    "recurring_max_staleness_days": [35, 45, 62],
    "dedupe_projection_against_explicit": ["credits_only", "all", "off"],
    # income
    "recurring_include_income": [True, False],
    "salary_projection_amount": ["last_occurrence", "median_of_last_n", "mean_of_last_n"],
    "salary_projection_n": [3, 6, "all"],
    "salary_projection_day": ["same_day_of_month", "same_interval"],
    "stopped_income_cutoff_days": [20, 35, 45, 62],
    "project_irregular_income": [False, True],
    # rows with a status
    "include_pending_debits": [True, False],
    "pending_debits_reserved_immediately": [False, True],
    "include_scheduled_debits": [True, False],
    "include_scheduled_credits": [True, False],
    "possible_duplicate_pending_debit": ["include", "exclude"],
    "linked_resolution": ["child_supersedes_parent", "none"],
    # messages + planner
    "apply_message_effects": [True, False],
    "temporary_income_change_scope": ["next_only", "all_future"],
    "count_one_time_arrears": [False, True],
    "require_completion_by_desired_date": [True, False],
    "installment_months_basis": ["number_of_payments", "span_months"],
    "payments_beyond_horizon": ["ignore", "count"],
    "rank_changes_by_count": [True, False],
    # window / checks / rounding
    "forecast_starts_day_0_or_1": [0, 1],
    "forecast_includes_day_90": [True, False],
    "earliest_date_window_anchor": ["request_date", "payment_date"],
    "salary_applied_before_expenses_same_day": [True, False],
    "min_balance_checked_after_payment": [True, False],
    "check_opening_balance": [True, False],
    "unsafe_if_equal_to_minimum": [False, True],
    "rounding_mode": ["floor_2dp", "round_2dp", "floor_int", "round_int"],
}

# Winning values that would be hard to defend financially, whatever the score says.
SUSPICIOUS = {
    ("include_pending_debits", False): "ignores money already committed by pending card charges",
    ("include_scheduled_debits", False): "ignores confirmed scheduled bills",
    ("include_scheduled_credits", False): "ignores the explicitly confirmed next salary",
    ("check_opening_balance", False): "lets a user who is already below the minimum pay",
    ("recurring_include_income", False): "no salary at all after today; contradicts sample request_02's dated earliest",
    ("project_irregular_income", True): "projects commissions/bonuses/gig pay the spec says not to count until settled",
    ("possible_duplicate_pending_debit", "exclude"): "drops an unresolved disputed debit (less safe)",
    ("rounding_mode", "round_2dp"): "rounding up can recommend a payment that breaks the minimum by a cent",
    ("rounding_mode", "round_int"): "rounding up can recommend a payment that breaks the minimum",
    ("stopped_income_cutoff_days", 62): "keeps projecting income that has been silent for two months",
    ("recurring_min_occurrences", 2): "two rows are thin evidence of a monthly bill",
    ("apply_message_effects", False): "ignores amendments / cancellations the spec says to use",
    ("require_completion_by_desired_date", False): "may recommend a plan that finishes after the deadline",
    ("payments_beyond_horizon", "count"): "judges installments by unforecast months after day 90",
    ("count_one_time_arrears", True): "counts a one-off adjustment before it settles",
}

_memo: dict = {}


def config_key(cfg: dict) -> str:
    return json.dumps(cfg, sort_keys=True, default=str)


def run(cfg: dict) -> list[dict]:
    key = config_key(cfg)
    if key not in _memo:
        engine.set_config(**cfg)
        _memo[key] = evaluate.score_rows(engine.get_data())
    return _memo[key]


def row_score(row: dict) -> float:
    return sum(w for col, w in WEIGHTS.items() if row["ok"][col])


def total(rows: list[dict]) -> float:
    return 100 * sum(row_score(r) for r in rows) / len(rows)


def row_exact(rows: list[dict]) -> int:
    return sum(all(r["ok"].values()) for r in rows)


def diff(before: list[dict], after: list[dict]) -> tuple[list[str], list[str]]:
    fixed, broken = [], []
    for b, a in zip(before, after):
        delta = row_score(a) - row_score(b)
        cols = [c for c in WEIGHTS if a["ok"][c] != b["ok"][c]]
        tag = f"{a['request_id']}({','.join(('+' if a['ok'][c] else '-') + short(c) for c in cols)})"
        if delta > 1e-9:
            fixed.append(tag)
        elif delta < -1e-9:
            broken.append(tag)
    return fixed, broken


def short(col: str) -> str:
    return {"amount_safe_to_pay": "amt", "affordability_status": "status", "earliest_date_for_full_payment": "earliest",
            "recommended_payment_method": "method", "payment_plan": "plan", "spending_changes_needed": "chg"}[col]


def guard(cur_rows, new_rows) -> tuple[bool, list[str], list[str]]:
    fixed, broken = diff(cur_rows, new_rows)
    ok = total(new_rows) > total(cur_rows) + 1e-9 and len(fixed) - len(broken) >= MIN_NET_ROWS
    return ok, fixed, broken


def coordinate_ascent(current: dict) -> tuple[dict, list[dict], dict]:
    records: dict[str, dict] = {}
    impact = {flag: 0.0 for flag in SEARCH_SPACE}
    for pass_no in range(1, MAX_PASSES + 1):
        adopted_this_pass = False
        for flag, values in SEARCH_SPACE.items():
            cur_rows = run(current)
            scores = {}
            rows_by_value = {}
            for v in values:
                rows_by_value[v] = run({**current, flag: v})
                scores[v] = total(rows_by_value[v])
            impact[flag] = max(impact[flag], max(scores.values()) - min(scores.values()))
            best = max(values, key=lambda v: (round(scores[v], 9), v == current[flag]))
            if best == current[flag]:
                continue
            ok, fixed, broken = guard(cur_rows, rows_by_value[best])
            rec = {"flag": flag, "from": current[flag], "to": best, "pass": pass_no, "stage": "ascent",
                   "delta": scores[best] - total(cur_rows), "fixed": fixed, "broken": broken,
                   "status": "adopted" if ok else "insufficient evidence"}
            if ok:
                current = {**current, flag: best}
                adopted_this_pass = True
                records[f"{flag}@{pass_no}"] = rec
            else:
                records.setdefault(f"{flag}@insufficient", rec)
                records[f"{flag}@insufficient"] = rec
        print(f"  pass {pass_no}: score {total(run(current)):.2f}, row-exact {row_exact(run(current))}/25, "
              f"{'adopted changes' if adopted_this_pass else 'no change'}")
        if not adopted_this_pass:
            break
    return current, list(records.values()), impact


def grid_search(current: dict, impact: dict) -> tuple[dict, dict | None]:
    top = [f for f, v in sorted(impact.items(), key=lambda kv: -kv[1]) if v > 0][:GRID_TOP_K]
    while top and len(list(itertools.product(*(SEARCH_SPACE[f] for f in top)))) > MAX_GRID:
        top.pop()
    combos = list(itertools.product(*(SEARCH_SPACE[f] for f in top)))
    print(f"  grid over {top} = {len(combos)} combos")
    cur_rows = run(current)
    best_cfg, best_rows = current, cur_rows
    for combo in combos:
        cfg = {**current, **dict(zip(top, combo))}
        rows = run(cfg)
        changes = sum(cfg[f] != current[f] for f in top)
        best_changes = sum(best_cfg[f] != current[f] for f in top)
        if total(rows) > total(best_rows) + 1e-9 or (abs(total(rows) - total(best_rows)) < 1e-9 and changes < best_changes):
            best_cfg, best_rows = cfg, rows
    if best_cfg == current:
        return current, None
    ok, fixed, broken = guard(cur_rows, best_rows)
    changed = {f: (current[f], best_cfg[f]) for f in top if best_cfg[f] != current[f]}
    rec = {"flag": " + ".join(changed), "from": {f: a for f, (a, _) in changed.items()},
           "to": {f: b for f, (_, b) in changed.items()}, "pass": "grid", "stage": "grid",
           "delta": total(best_rows) - total(cur_rows), "fixed": fixed, "broken": broken,
           "status": "adopted" if ok else "insufficient evidence"}
    return (best_cfg if ok else current), rec


def print_table(rows: list[dict], label: str) -> None:
    t = evaluate.column_table(rows)
    print(f"\n{label}: weighted score {total(rows):.2f}   row-exact {t['row_exact']}/{t['n']}")
    for col in evaluate.COLUMNS + ["amount_safe_to_pay (tolerance)"]:
        print(f"    {col:<34} {t[col]:>3}/{t['n']}")


def main() -> None:
    t0 = time.time()
    start = {flag: engine.CONFIG[flag] for flag in SEARCH_SPACE}
    if OUT_PATH.exists():  # continue from the previously adopted flags
        previous = json.loads(OUT_PATH.read_text(encoding="utf-8")).get("fitted_flags", {})
        start.update({k: v for k, v in previous.items() if k in SEARCH_SPACE})
    start_rows = run(start)
    print_table(start_rows, "START (current CONFIG)")

    print("\n== coordinate ascent ==")
    current, records, impact = coordinate_ascent(dict(start))
    print("\n== grid search over top flags ==")
    current, grid_rec = grid_search(current, impact)
    if grid_rec:
        records.append(grid_rec)

    final_rows = run(current)
    print_table(final_rows, "FINAL")

    print("\n== flag impact (max score spread seen while varying the flag alone) ==")
    for flag, v in sorted(impact.items(), key=lambda kv: -kv[1]):
        if v > 0:
            print(f"    {flag:<42} {v:6.2f}")

    print("\n== ranked changes (adopted and rejected) ==")
    for rec in sorted(records, key=lambda r: -abs(r["delta"])):
        print(f"\n  [{rec['status'].upper()}] {rec['flag']}: {rec['from']} -> {rec['to']}  "
              f"(stage {rec['stage']}, pass {rec['pass']}, score {rec['delta']:+.2f}, "
              f"net rows {len(rec['fixed']) - len(rec['broken']):+d})")
        print(f"      fixed : {', '.join(rec['fixed']) or '-'}")
        print(f"      broken: {', '.join(rec['broken']) or '-'}")
        if rec["status"] == "adopted":
            pairs = rec["to"].items() if isinstance(rec["to"], dict) else [(rec["flag"], rec["to"])]
            for f, v in pairs:
                if (f, v) in SUSPICIOUS:
                    print(f"      REVIEW: {f}={v!r} - {SUSPICIOUS[(f, v)]}")

    engine.set_config(**current)
    out = {
        "config": {k: v for k, v in engine.CONFIG.items()},
        "fitted_flags": current,
        "changed_from_start": {f: {"from": start[f], "to": current[f]} for f in SEARCH_SPACE if start[f] != current[f]},
        "score_start": total(start_rows), "score_final": total(final_rows),
        "row_exact_start": row_exact(start_rows), "row_exact_final": row_exact(final_rows),
        "columns_start": evaluate.column_table(start_rows), "columns_final": evaluate.column_table(final_rows),
        "records": records, "weights": WEIGHTS, "min_net_rows": MIN_NET_ROWS,
    }
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT_PATH}  ({time.time() - t0:.0f}s, {len(_memo)} configs evaluated)")


if __name__ == "__main__":
    main()
