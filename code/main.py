"""Buy or Wait? - entry point.

    python3 code/main.py

Reads dataset/, applies the fitted CONFIG (code/best_config.json when present) and writes <repo root>/output.csv.
Paths are resolved from this file, so the output lands in the repository root from any working directory.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
ROOT = CODE_DIR.parent
OUTPUT_PATH = ROOT / "output.csv"
BEST_CONFIG_PATH = CODE_DIR / "best_config.json"
sys.path.insert(0, str(CODE_DIR))

import engine  # noqa: E402

COLUMNS = ["request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method", "payment_plan",
           "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation"]


def apply_fitted_config(path: Path = BEST_CONFIG_PATH) -> None:
    if path.exists():
        flags = json.loads(path.read_text(encoding="utf-8")).get("fitted_flags", {})
        engine.set_config(**{k: v for k, v in flags.items() if k in engine.CONFIG})


def request_ids_in_order() -> list[str]:
    with open(engine.DATASET_DIR / "requests.csv", newline="", encoding="utf-8") as fh:
        return [row["request_id"] for row in csv.DictReader(fh)]


def predict_all() -> list[dict]:
    import planner
    data = engine.get_data()
    return [{"request_id": rid, **{k: v for k, v in planner.recommend(data.requests[rid], data).items() if k in COLUMNS}}
            for rid in request_ids_in_order()]


def write_output(rows: list[dict], path: Path = OUTPUT_PATH) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    apply_fitted_config()
    rows = predict_all()
    write_output(rows)
    print(f"wrote {len(rows)} rows to {OUTPUT_PATH}")
    import validate
    errors = validate.validate(OUTPUT_PATH)
    if errors:
        print("VALIDATION FAIL")
        for check, ids in errors.items():
            print(f"  {check}: {', '.join(ids[:20])}")
        sys.exit(1)
    print("VALIDATION PASS")


if __name__ == "__main__":
    main()
