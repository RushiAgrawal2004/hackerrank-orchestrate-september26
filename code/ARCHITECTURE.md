# Architecture

```
dataset/*.csv ──► engine.load_all ──────────────────────────────────────────────┐
  profiles, events, fx, requests,     parse, FX to home currency (dated rate),    │
  options, messages, images           linked_event_id: child supersedes parent    │
                                                                                  ▼
image_amounts.json ─(cached vision reads, untrusted → numbers only)──► blank amounts filled
messages.csv ─► message_rules ─(regex facts + support check, untrusted)──► ledger effects
                                                                                  │
                  engine.build_ledger(user, request_date)  ◄──────────────────────┘
                   explicit future rows (pending debits, scheduled bills, confirmed salary)
                 + monthly series projected forward (rent, subscriptions, salary if not stale)
                 + irregular spending projected (daily average per category)
                 + message effects (amend / delay / stop / resume income, rent increase)
                                                                                  │
                  engine.simulate / day_profile ─► max_safe_today, earliest_full_date
                                                                                  │
                  planner.search ─► winner + status ─► explain ─► output row
                                                                                  │
                  main.py ─► output.csv (repo root) ─► validate.py (hard gate, exit 1 on FAIL)
```

## Where a model is used — and where it deliberately is not

| stage | model? | why |
|---|---|---|
| Reading 16 receipt / pay-slip images | **yes, once** (Claude vision; cached in `image_amounts.json`; batch path `extract_images.py`) | pixels need vision. The output is only `{amount, currency, date, merchant, confidence, notes}` |
| Reading 215 messages | **no**: regex rules | the text is formulaic (215/215 coverage); rules are free, reproducible and testable |
| Forecast, safety check, plan choice, status, explanation | **never** | the decision must be auditable and deterministic; a model would add variance, cost and an injection surface, and nothing the rules can't do |

## The 90-day safety check

- The balance walk starts at `current_available_balance` on `request_date` and runs day by day through request_date + 90.
- **Within a day:** credits apply before debits, and a plan payment applies after the same-day debits.
- **The check** runs after every movement, and after the opening balance, against `minimum_balance_to_keep`. Balance equal to the minimum still counts as safe.
- **Included:** pending debits, scheduled debits and credits, projected monthly series, irregular spending averages, and message effects.
- **Excluded:** pending credits, failed or cancelled rows, superseded chain parents, unrealized valuations, and unsupported income.
- **Derived values:** `max_safe_today` is the largest single payment today that keeps every later checkpoint ≥ minimum. A fast one-walk path is proven identical to binary search. `earliest_full_date` is the first day a full single payment passes the same check. Both ignore spending changes and payment preferences, because they measure capacity.

## Plan search and the six tie-breakers

**Candidates.** Full payment today, every supplied installment schedule (payment k on first_date + k × frequency), partial (safe today + remainder on the earliest date) and wait (full on the earliest date). Each is crossed with every subset of up to 3 spending changes (stop, or reduce to `minimum_allowed_amount`, on flexible expenses in categories the user permits).

**Eligibility first:**
- The method must be in `payment_methods_user_will_consider`.
- Installments must be within `max_installment_months`.
- Partial requires `allows_partial_payment`, 0 < safe < requested, and earliest date ≤ deadline.
- Wait requires full payment to become safe later and full payment to be accepted.
- The plan must complete by `desired_completion_date`.

Every eligible candidate is simulated, and the safe ones are sorted by one tuple key:

1. completes by `desired_completion_date`
2. requires no spending changes (then fewer changes)
3. lowest total paid
4. earliest first payment
5. fewest payments
6. lowest `payment_option_id`

The winner fixes method, plan and changes. Status follows from it:

| winner | status |
|---|---|
| full payment today, no changes | affordable_now |
| wait | affordable_later |
| partial, installments, or changes | affordable_with_plan |
| none | not_affordable / not_recommended |

## The validator as the final gate

`main.py` always ends with `validate.py`, which checks:
- row count; missing, extra or duplicate ids; exact columns and order;
- 0 ≤ amount ≤ requested;
- enums and date formats; affordable_now ⇒ earliest == request_date;
- plan format and chronology;
- partial = 2 payments summing to the request on the right dates;
- installments identical to a supplied option;
- at most 3 changes, only on flexible events of the same user, never below the minimum, never stop and reduce the same event;
- non-empty explanation.

Any failure exits 1, so a broken file cannot be shipped silently.

## Untrusted-input boundary

- **Images and messages** can supply facts (numbers, dates, percentages) only. They never supply instructions, and never decisions.
- **Messages:**
  - A claim changes the ledger only if the user's own rows support it.
  - Salary facts must come from the employer (enforced by test after an injection test caught a merchant message raising salary).
  - Income without a backing row (first salaries, invoices, the salary claim inside message_86) is rejected.
  - Instruction-like sentences are logged to `blocked_instructions.json` and never executed: payment demands, "should be removed/included", third-party income assertions.
- **Images:** the extraction prompt tells the model to ignore embedded instructions and list them, and the cache stores only the fixed JSON fields. Every chosen figure carries a stated rule: net over gross; printed grand total over breakdown; amount valid on the settlement date.
