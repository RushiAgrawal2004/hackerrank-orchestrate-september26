# DECISIONS

Every non-obvious choice in the build: the problem, the options, what was chosen, the evidence on `dataset/sample_requests.csv` (request_ids fixed / broken), the risk on the hidden 250, and what was rejected. Flags live in `CONFIG` in `code/engine.py`; fitted values are in `code/best_config.json`.

Sample score history (25 rows, exact match):

| stage | amount | status | method | plan | earliest | changes | row-exact |
|---|---|---|---|---|---|---|---|
| Phase 1 baseline | 4 | 8 | 11 | 11 | 9 | 22 | 3 |
| Phase 2 (variable spending) | 4 | 9 | 12 | 12 | 18 | 22 | 3 |
| Phase 3 before planner (images + messages on) | 4 | 9 | 12 | 12 | 17 | 22 | 3 |
| **Phase 3 final (planner)** | **4** | **19** | **22** | **20** | **17** | **22** | **4** |

---

## D0. Submission contract

- **Problem:** `code/main.py` was empty (0 bytes), so `python3 code/main.py` produced nothing. `log.txt` must sit next to `AGENTS.md`.
- **Chosen:**
  - `main.py` resolves paths from `__file__` and writes `<repo root>/output.csv` from any working directory.
  - It runs the validator afterwards and exits 1 on FAIL.
  - `log.txt` has been appended in the repo root since the first turn.
- **Evidence:** run from an unrelated working directory, the root `output.csv` has 251 lines (header + 250), and no stray copies exist in `code/` or the cwd. Validator PASS.
- **Risk:** on the build machine `python3` is the Windows Store stub, so testing used `python` (3.13). The code is stdlib-only for Python ≥ 3.10.
- **Rejected:**
  - Writing `output.csv` relative to the current working directory, or next to the code: either depends on where the command is launched and can miss the required repo-root location.
  - A shell or batch wrapper around `main.py`: `python3 code/main.py` is the documented entry point and must work on its own on every OS.

## D1. Part 0 — `amount_safe_to_pay` inverse problem (KNOWN LIMITATION)

- **Problem:** the engine's amount is wrong on 21/25 samples, and too high on 17 of those 21.
- **Tested, in order.** All failed:

| hypothesis | test | result |
|---|---|---|
| H0a pending debits reserved on request_date | `pending_debits_reserved_immediately=True` | **0 of 25 amounts change.** Every pending debit settles 1–5 days out, before the binding day (day 5–14), so it is already inside the 90-day minimum. Rejected. |
| H0b pending credits excluded | scan of all 275 ledgers | holds: 0 pending credit rows in any ledger |
| H0c salary only on settlement date | scan of all 275 ledgers | holds: 0 explicit credits off their settlement date, 0 projected credits on/before request_date, 0 projected credits before a confirmed credit in the same month |
| H1 missing spending rate | delta ÷ days-to-binding as a multiple of the user's own 30-day all-category daily average | not constant: median 0.42, range −1.41 … 13.57 |
| H2 one missing item | delta vs every single event amount of the user (±1%) | only two hits (request_05 ≈ payroll 14,740; request_10 ≈ delivery plan 1,895). Both are rows where my amount is capped at the request, so they are coincidences |
| H3 extra safety buffer | delta ÷ minimum / balance / requested vs clean fractions | no consistent fraction |
| H4 excluded class added back | include pending credits; keep/exclude possible duplicates; investment_purchase as recurring; min occurrences 2; day-of-month spread 3; several rows per month; ignore links | 0 amounts change (scheduled debits removed makes 2 worse) |
| H5 boundary / check / rounding | day 90 excluded; start day 1; strict `>` minimum; end-of-day check; debits before credits; opening check off; round_2dp; floor_int | exact stays 4. floor_int moves 14 rows closer but can never be exact (sample amounts carry cents) |
| extra: every irregular description projected monthly (hint from event_989) | 54 combinations | best 3 exact, all capped rows — worse |

- **The 4 exact rows share one property:** request_01, 09, 12 and 16 all have sample amount == `requested_amount`. They match because the cap hides the forecast error, so they carry no information about the forecast.
- **Chosen:**
  - **Freeze** the amount logic at `variable_spending_mode=daily_average`, protected categories, 90 days, mean, even daily. This was adopted in Phase 2: +8 earliest dates, 0 broken.
  - Stop searching.
- **Best explanation:** the key likely forecasts irregular spending from generator-internal parameters that the history rows only approximate. On 15/21 rows the implied extra spend is 0.7–1.3× the user's own 30-day average, but never exactly.
- **Risk on hidden 250:** amount exact matches will be rare wherever the key's amount < requested (roughly 80% of samples). Status, method and plan are robust to moderate amount error; earliest dates mostly survive because salary days dominate them.
- **Rejected:** further coordinate search of spending flags (1,878 combinations already tried with 0 exact matches).

### D1b. Final amount diagnostic — solve for the difference (45-minute cap; result: FAILURE)

- **Method, for each of the 21 wrong rows:**
  - `my_outflow` = balance − my lowest checkpoint (from request_date to my binding day).
  - `implied` = balance − minimum − sample amount.
  - `residual` = my_outflow − implied. Negative means the key has more outflow than my forecast.
- **Residual table:**

| request | cur | balance | my_outflow | implied | residual | % of balance | my binding day |
|---|---|---|---|---|---|---|---|
| request_02 | IDR | 60,383,889.20 | 9,873,398.04 | 13,996,350.00 | −4,122,951.96 | −6.83% | 2025-08-13 |
| request_03 | IDR | 5,810,300.00 | 2,043,766.85 | 2,268,600.00 | −224,833.15 | −3.87% | 2019-09-14 |
| request_04 | IDR | 52,206,950.00 | 10,455,088.43 | 13,118,550.00 | −2,663,461.57 | −5.10% | 2024-06-14 |
| request_05 | ZAR | 46,475.10 | 4,656.46 | 32,638.10 | −27,981.64 | −60.21% | 2025-11-14 |
| request_06 | EUR | 1,942.40 | 457.29 | 539.10 | −81.81 | −4.21% | 2026-01-14 |
| request_07 | INR | 218,945.56 | 171,193.71 | 38,775.00 | +132,418.71 | +60.48% | 2024-12-04 |
| request_08 | EUR | 1,536.57 | 424.95 | 452.00 | −27.05 | −1.76% | 2025-05-08 |
| request_10 | INR | 750,155.00 | 510,178.73 | 512,055.00 | −1,876.27 | −0.25% | 2025-03-06 |
| request_11 | IDR | 63,531,795.00 | 13,170,817.10 | 16,880,550.00 | −3,709,732.90 | −5.84% | 2025-05-14 |
| request_13 | EUR | 2,789.52 | 669.03 | 1,056.12 | −387.09 | −13.88% | 2024-05-14 |
| request_14 | EUR | 3,931.74 | 1,142.10 | 1,134.00 | +8.10 | +0.21% | 2025-08-14 |
| request_15 | EUR | 1,770.05 | 409.03 | 487.00 | −77.97 | −4.41% | 2026-01-14 |
| request_17 | INR | 550,379.58 | 131,494.83 | 140,430.00 | −8,935.17 | −1.62% | 2026-03-14 |
| request_18 | EUR | 2,486.00 | 391.39 | 624.00 | −232.61 | −9.36% | 2026-07-11 |
| request_19 | INR | 199,545.00 | 75,839.46 | 77,925.00 | −2,085.54 | −1.05% | 2024-09-14 |
| request_20 | INR | 102,609.05 | 23,148.53 | 32,709.05 | −9,560.52 | −9.32% | 2026-02-13 |
| request_21 | USD | 3,911.35 | 456.97 | 568.00 | −111.03 | −2.84% | 2026-04-14 |
| request_22 | EUR | 1,132.46 | 151.68 | 157.00 | −5.32 | −0.47% | 2024-12-14 |
| request_23 | ZAR | 51,957.90 | 14,862.23 | 15,805.90 | −943.67 | −1.82% | 2025-05-14 |
| request_24 | INR | 85,045.00 | 16,827.58 | 20,625.00 | −3,797.42 | −4.47% | 2026-01-14 |
| request_25 | IDR | 32,063,050.00 | 5,503,658.08 | 7,258,950.00 | −1,755,291.92 | −5.47% | 2024-03-14 |

- **Subset-sum** (≤ 3 items, tolerance 0.01 then 1.0). The candidates per row were:
  - every ledger item up to my binding day, removable (variable spending collapsed to one total per category);
  - every real row the engine excluded (failed, cancelled, pending credit, possible duplicate, beyond window);
  - every un-projected description group's next monthly occurrence.
- **Subset-sum result:**
  - **15 of 21 rows:** no subset within 1.0.
  - **6 rows with hits:** all have small residuals (EUR/USD), where many small items combine.
    - request_08: 27 hits (noise).
    - request_06: 2 hits (groceries + transport rows).
    - request_13: remove salary + all groceries (not plausible).
    - request_21: stop cloud storage + groceries + transport rows.
    - request_22: stop music subscription + one transport row.
  - The most frequent attribute across hits is "an irregular transport/groceries row added back". That is H1 (a spending-rate difference) again, not a misclassification.
- **Alternative horizons for this column:** `90_days`, `to_desired_completion_date`, `to_next_salary_date` and `to_end_of_month` all give 4/25 exact, 4/25 within 1%, and 0 exact on uncapped rows. My binding day falls before every horizon end, so the horizon never changes the amount.
- **Verdict:**
  - No single event_type, status, category or projection source recurs across the residuals, so there is no one-line misclassification fix.
  - 19 of 21 residuals are negative, at 0.2–14% of balance: the key holds more irregular outflow before the low point than any rule derived from the history rows.
  - request_05 (−60%) and request_07 (+60%) are income-structure differences (salary projection or its absence), not spending.
  - The amount logic stays frozen.
- **Rejected:**
  - A correction term derived from the residuals (for example a buffer scaled to each row's gap): it reproduces the 25 samples by construction and has no evidence behind it for the hidden 250.
  - Subset sizes above 3: candidate pools hold 6–93 items, so larger subsets would match almost any residual by chance.
  - Adopting an alternative amount horizon: none of the four changed a single amount.

## D2. Image amounts (no API)

- **Problem:** 16 events have blank amounts. No API key was available.
- **Options:**
  1. Run `extract_images.py`: impossible without credentials.
  2. Read the images interactively and cache the values.
  3. Leave the rows blank: forbidden, a blank is not zero.
- **Chosen:** option 2.
  - Values are in `code/image_amounts.json` with `source: "vision_interactive"`, `confidence`, `ambiguity_note` and `chosen_rule`.
  - `extract_images.py` stays as the reproducible batch path (`--dry-run` works). Everything is cached, so it makes no calls.
- **Rules applied to ambiguous documents:**
  1. Prefer the printed grand total over a computed breakdown. event_6859: printed 3,650 vs breakdown sum 3,150 → **3,650**.
  2. Prefer net over gross for pay. event_253: net 4,365,000 vs gross 4,780,800 → **4,365,000**.
  3. Prefer the amount valid on the row's settlement date:
     - event_1442 "Outstanding rent balance": balance due 100,000 vs total 200,000 → **100,000**.
     - event_1786: 704.05 if paid by 06-Feb vs 822.05 after, and the row settles 02-09 → **822.05**.
  - Recorded caveat, event_3231: the supplied 8,528.10 is the pre-rounding "Total". The printed "Grand Total (RS)" is 8,528. The supplied value was kept; the difference is INR 0.10 on a historical row outside the forward ledger.
  - event_7307 is USD 33.50. The engine converts it with the 2025-10-01 USD→INR rate.
- **Risk:** only 4 of the 16 rows are future cash (event_1442, 1786, 6033, 6859). Two belong to sample users 16 and 20, two to hidden users 64 and 73. The rest only shape spending averages and salary history.
- **Rejected:** using "balance due" semantics for every receipt; treating late-fee amounts as optional.

## D3. Messages — deterministic parser (`code/message_rules.py`)

- **Problem:** 215 messages amend, cancel, delay or confirm facts. No LLM is allowed.
- **Chosen:**
  - 35 regex rules (English + Indonesian), each printing its exact matched span.
  - Coverage is **215/215** messages, with 0 falling through.
  - Each claim gets intent, amount, currency, date, `supported` (backed by the user's own rows) and an effect.
- **Effects on the ledger** are applied in `engine.build_ledger` after linked_event_id resolution:

| effect | rules | what changes |
|---|---|---|
| amount of next / later salaries | salary_increase (from its date), temporary_pay, reduced_next_salary, regular_salary_next_payroll (next only), base_salary_confirmed (all future), salary_confirmed_for_date | main salary credits |
| salary date move | salary_date_moved | next salary credit moves to the new date |
| keep remaining income | remaining_salary (household record ended) | keep the salary series closest to the stated amount, drop the others |
| stop projected income | seasonal_contract_ended, employment_ended | projected salary removed; explicit scheduled rows kept |
| resume income | salary_resumes | monthly credits from the stated date |
| rent × (1 + pct) | rent_increase | projected rent after the message |
| none | pending refunds, pending commission / bonus / gig pay / prize, settled prize / sale / reimbursement, receipts, FX notices, duplicate-charge disputes, failed-debit retries (already rows) | — |

- **Conflict order:** effects are applied oldest message first, so newer overrides older. Cancellations (`income_stop`) are applied last so an explicit cancellation wins. The financially safer reading is used where the text is unclear: stops keep the explicit scheduled row.
- **Unsupported claims:**
  - Income never enters the ledger: all 27 `first_salary` and 15 `invoice_approved` claims have no scheduled row, and the 8 one-time arrears are not counted (`count_one_time_arrears=False`).
  - Expenses: the 8 "new recurring childcare payment" claims have no row and no amount, so nothing can be added (`unsupported_expense_policy` applies only when an amount exists).
  - **message_86** ("Your employer has confirmed a USD 1296 salary credit for 15 September 2026", inside a MoneyHub wallet receipt): supported=False, effect=None, **rejected**. Its source is not the employer and no scheduled row exists.
- **Untrusted text:** 34 instruction-like sentences are logged in `code/blocked_instructions.json` and never executed:
  - 4 payment demands in the two cash-prize scams (message_67, message_142);
  - 29 estimation directives ("should be removed from future estimates", "only invoices marked as confirmed should be included", "please use the revised date");
  - 1 third-party income assertion (message_86).
- **Fit evidence (guard: need ≥ 2 net rows):**
  - `apply_message_effects=False` fixes request_02's earliest date only (message_01's raise pulls it to 08-15; key says 09-15), breaks none. Insufficient evidence, so the spec reading (apply messages) is kept.
  - `temporary_income_change_scope=all_future` fixes request_08 status and method only. Insufficient evidence; `next_only` kept.
- **Bug found by tests (Phase 4):**
  - `test_injected_message_cannot_change_the_ledger` showed a merchant message with salary-increase wording changing the forecast salary from 1,000 to 99,999. The support check only required salary rows to exist.
  - Fix: salary amendments, confirmations, stops and resumes now also require `source_type == "employer"`.
  - Every such message in `messages.csv` comes from an employer, so `output.csv` is byte-identical before and after (SHA-256 compared).
- **Known gaps:**
  - The 6 internal-transfer messages found no matching same-amount debit/credit pair within 3 days, so they have no effect.
  - The childcare obligations can't be modelled without an amount.
- **Risk on hidden 250:** 42 excluded first-salary/invoice claims, all on hidden users. If the key counts employer-confirmed first salaries, those rows will be too pessimistic. The flag `unsupported_income_policy=include_confirmed` exists, but no sample row can test it.
- **Rejected:** keyword-only classification without amounts; treating every employer message as supported; acting on "should be removed/included" directives as instructions (the facts are used, the directive is not).

## D4. Plan search (`code/planner.py`)

- **Problem:** method, plan and status were Phase 1 dummy logic.
- **Chosen:**
  - **Candidates:** full payment today · every installment option with its exact schedule (payment k on first_date + k × frequency) · partial (amount_safe_to_pay today + remainder on earliest_date_for_full_payment) · wait (full amount on earliest date). Each is crossed with every subset of up to 3 spending changes, including the empty set. not_recommended is the fallback.
  - **Eligibility before simulation:**
    - Methods must be in `payment_methods_user_will_consider`.
    - wait needs full_payment accepted and earliest > request_date.
    - Partial needs `allows_partial_payment`, 0 < safe < requested, and earliest ≤ desired date.
    - Installments need `number_of_payments ≤ max_installment_months`.
    - Spending changes are only for detected monthly series: stop when flexibility allows it and the category is in `expense_categories_user_is_willing_to_stop`; reduce to `minimum_allowed_amount` when the category is in `..._willing_to_reduce`. The same event can't be both stopped and reduced.
  - **Safety:** `engine.simulate` with the plan's payments and changes.
  - **Ranking:** one tuple key = (completes by desired date, needs changes, number of changes, total paid, first payment date, number of payments, payment_option_id number, change ids).
  - **Status:** full today without changes → affordable_now; full with changes, partial or installments → affordable_with_plan; wait → affordable_later; none → not_affordable. earliest_date_for_full_payment is still the capacity date, independent of method.
- **New flags:**

| flag | default | alternatives | fit evidence |
|---|---|---|---|
| `require_completion_by_desired_date` | True (the spec's safety definition includes the deadline) | False: rank only | no change on samples |
| `installment_months_basis` | number_of_payments | span_months | no change |
| `payments_beyond_horizon` | ignore (only payments inside the 90-day forecast are simulated) | count | no change |
| `rank_changes_by_count` | True (my addition inside key 2) | False | no change |

- **Evidence:** status 9 → 19, method 12 → 22, plan 12 → 20, row-exact 3 → 4, with no column made worse.
- **Remaining misses and their causes:**
  - request_05: the forecast is too optimistic, so it says affordable_now; the key says not_affordable.
  - request_06 and request_21: the forecast is too optimistic, so no spending change is needed. The key needs stop / stop + reduce.
  - request_11: the key reduces event_989, an irregular dining series. The engine only proposes changes on monthly series, so it can never produce this.
  - request_07 and request_08: the forecast is too pessimistic, so not_recommended. The key says installments / wait.
  - request_18: the wait date is one month early.
  - request_19: partial amounts inherit the amount error.
- **Risk:** plan choice is only as good as the forecast near the binding day. The ranking and eligibility logic themselves are spec-literal.
- **Rejected:**
  - choosing among change subsets by largest or smallest saving (not in the spec; fewest changes reproduces request_21's pair);
  - allowing plans that finish after the deadline;
  - simulating installments beyond day 90 against an empty ledger.

### D4b. Spending changes on irregular flexible expenses

- **Problem:** request_11's sample reduces `event_989` ("Weekend food delivery", reducible dining, 2 irregular rows). The planner only proposed changes on detected monthly series.
- **Chosen:**
  - Every flexible (non-fixed) expense group is now eligible for stop / `reduce_to`, monthly or irregular (`engine.irregular_flexible_series`: description + category, latest row inside the lookback).
  - Category permission and `minimum_allowed_amount` are respected.
  - `series_for_event` resolves both kinds, so `simulate()` applies the change.
  - request_11 now gets `reduce_to:event_989:665950` plus four other dining groups as candidates.
- **A change only matters if the item is in the forecast.** New flag `irregular_flexible_projection`:

| value | amount | status | method | plan | earliest | changes | row-exact | fixed | broken |
|---|---|---|---|---|---|---|---|---|---|
| none (default) | 4 | 19 | 22 | 20 | 17 | 22 | 4 | — | — |
| monthly_mean | 3 | 19 | 21 | 20 | 17 | 22 | 3 | request_18, request_21 | request_12 (5 columns), request_17 |
| monthly_mean_from_start | 3 | 18 | 19 | 18 | 17 | 21 | 3 | request_18 | request_11, 12, 17, 21 |

- **Decision:** keep `none`. Net rows are 0 or negative, so it fails the guard.
- **Why request_11 is still missed:** my forecast already finds full payment safe today (amount too high, D1). The planner never needs a change, so the new candidate is never selected.
- **Risk on hidden 250:** low. With `none`, irregular candidates are only used when a plan would otherwise be unsafe, and each reduction respects the minimum allowed amount.
- **Rejected:** projecting irregular flexible groups by default; allowing reductions below `minimum_allowed_amount`.

## D5. Validator (`code/validate.py`)

- **Checks, each a hard fail:**
  - row count; missing, extra or duplicate request_id; exact column names and order;
  - amount format and 0 ≤ amount ≤ requested;
  - status and method enums; date format; affordable_now ⇒ earliest == request_date;
  - plan format, chronological order, no payment before request_date;
  - status ↔ method consistency; full/wait = one payment of the full amount;
  - partial = exactly 2 payments summing to requested, on request_date and earliest date, allowed, within the deadline;
  - installments exactly equal to a supplied option's schedule;
  - spending changes: at most 3, known event of the same user, flexible, stop only on stoppable, reduce only on reducible and ≥ minimum_allowed_amount, no event changed twice;
  - non-empty explanation.
- **Evidence:** the final `output.csv` passes. A corrupted copy with 8 injected faults fails every one (row count, duplicate id, negative amount, affordable_now without date, illegal status, foreign/non-flexible event, blank explanation, altered installment schedule), with exit code 1.
- **Rejected:**
  - A warn-only validator: a malformed row would still ship.
  - Auto-repairing invalid rows inside the validator: it would hide planner bugs. Fixes belong in the planner; the validator only judges and exits 1.

## D6. Explanations (`code/explain.py`)

- **Chosen:**
  - Template sentences copied from the sample styles (pay today / use N installments / pay X today and the remaining Y on D / pay in full on D / do not make this payment).
  - A second sentence gives concrete engine facts: balance today, and the lowest projected balance under the recommended plan with its date.
  - For not_recommended, the "Although X is available today" variant is used when partial payment is the user's only method, the request allows it, and something is safe today; otherwise the "None of the available options…" variant.
  - Checked against every sample whose expected method is not_recommended. The first rule (neither full nor installments) differed on request_15, whose request doesn't allow partial payment; the corrected rule was re-checked. request_05 isn't comparable: the engine recommends full payment there (D4).
- **Rejected:** free text; any model call.

## D7. Flag fitting in Phase 3 (`code/fit_flags.py`)

- **Setup:** started from the Phase 2 fitted flags; 38 flags searched; score = amount 30%, status 25%, earliest 20%, method 10%, plan 10%, changes 5%.
- **Outcome:** the guard adopted nothing (58.60 before and after). Rejected for insufficient evidence (1 net row each):

| candidate | fixes | breaks |
|---|---|---|
| `salary_projection_amount`: last → mean_of_last_n | request_08 (status, earliest, method, plan) | — |
| `temporary_income_change_scope`: next_only → all_future | request_08 (status, method) | — |
| `apply_message_effects`: True → False | request_02 (earliest) | — |

- **Grid search:** the top 6 flags (192 combinations) found nothing better.
- **Risk:** these one-row wins may be real, but 25 rows can't distinguish them from noise.
- **Rejected:**
  - Adopting the three one-row wins anyway: each is indistinguishable from noise on 25 rows, and one (ignoring messages) contradicts the spec's instruction to use them.
  - Lowering the guard to 1 net row: with 38 flags searched, at least one spurious one-row gain is expected by chance alone.

## Known limitations (summary)

1. **`amount_safe_to_pay` exact accuracy is 4/25**, and the 4 are capped rows (D1).
2. Spending changes are only proposed for monthly series, so irregular reducible dining (request_11) is out of reach.
3. Employer-confirmed first salaries and approved invoices without a backing row are excluded, per spec. This is untestable on the samples (D3).
4. Internal-transfer messages have no effect: no matching pair found.
5. Image amounts were read interactively; token usage for those readings was not metered (`code/evaluation/usage_report.md`).
