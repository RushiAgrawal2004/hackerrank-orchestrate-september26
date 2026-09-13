"""Validator negative tests (the 8 injected faults) and the output.csv contract on the real 250 requests."""
from __future__ import annotations

import copy
import csv

import pytest

import engine as E
import main
import validate


@pytest.fixture(scope="module")
def output_rows():
    saved = copy.deepcopy(E.CONFIG)
    main.apply_fitted_config()
    rows = main.predict_all()
    E.set_config(**saved)
    return rows


def write(path, rows, columns=None):
    columns = columns or main.COLUMNS
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_output_contract(output_rows, tmp_path):
    path = write(tmp_path / "output.csv", output_rows)
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        body = list(reader)
    assert header == main.COLUMNS
    assert len(body) == 250 and sum(1 for _ in open(path, encoding="utf-8")) == 251
    assert [r[0] for r in body] == main.request_ids_in_order()
    assert {r[2] for r in body} <= validate.STATUSES
    assert {r[3] for r in body} <= validate.METHODS
    assert validate.validate(path) == {}


def first(rows, predicate):
    return next(i for i, r in enumerate(rows) if predicate(r))


def fault_duplicate_row(rows):
    rows.append(dict(rows[7]))


def fault_missing_row(rows):
    rows.pop()


def fault_negative_amount(rows):
    rows[0]["amount_safe_to_pay"] = "-5"


def fault_affordable_now_without_date(rows):
    rows[first(rows, lambda r: r["affordability_status"] == "affordable_now")]["earliest_date_for_full_payment"] = ""


def fault_illegal_status(rows):
    rows[1]["affordability_status"] = "maybe"


def fault_foreign_event_change(rows):
    rows[5]["spending_changes_needed"] = "stop:event_01"   # belongs to another user and is not flexible


def fault_blank_explanation(rows):
    rows[6]["decision_explanation"] = " "


def fault_altered_installments(rows):
    i = first(rows, lambda r: r["recommended_payment_method"] == "installments")
    rows[i]["payment_plan"] = rows[i]["payment_plan"] + "|2099-01-01:1"


FAULTS = [
    (fault_duplicate_row, {"duplicate_request_id", "row_count"}),
    (fault_missing_row, {"missing_request_id", "row_count"}),
    (fault_negative_amount, {"amount_format"}),
    (fault_affordable_now_without_date, {"affordable_now_earliest_not_request_date"}),
    (fault_illegal_status, {"illegal_affordability_status"}),
    (fault_foreign_event_change, {"spending_change_unknown_event"}),
    (fault_blank_explanation, {"empty_explanation"}),
    (fault_altered_installments, {"installments_not_matching_option"}),
]


@pytest.mark.parametrize("mutate,expected_checks", FAULTS, ids=[f.__name__ for f, _ in FAULTS])
def test_injected_fault_fails(output_rows, tmp_path, mutate, expected_checks):
    rows = copy.deepcopy(output_rows)
    mutate(rows)
    errors = validate.validate(write(tmp_path / "bad.csv", rows))
    assert expected_checks <= set(errors), errors


def test_wrong_column_order_fails(output_rows, tmp_path):
    swapped = main.COLUMNS[:1] + main.COLUMNS[2:3] + main.COLUMNS[1:2] + main.COLUMNS[3:]
    errors = validate.validate(write(tmp_path / "bad.csv", output_rows, columns=swapped))
    assert "column_names_or_order" in errors


def test_partial_payment_must_sum_to_request(output_rows, tmp_path, real_data):
    rows = copy.deepcopy(output_rows)
    i = first(rows, lambda r: r["recommended_payment_method"] in ("full_payment", "wait", "installments"))
    req = real_data.requests[rows[i]["request_id"]]
    rows[i].update(recommended_payment_method="partial_payment", affordability_status="affordable_with_plan",
                   payment_plan=f"{req.request_date}:1|{req.desired_completion_date}:2")
    assert "partial_payment_invalid" in validate.validate(write(tmp_path / "bad.csv", rows))
