# Results on `dataset/sample_requests.csv` (25 solved rows)

## How to run the scorer

```bash
python3 code/evaluation/main.py          # repo layout; Windows: python code/evaluation/main.py
python3 code/evaluation/main.py --quiet  # summary only
```

The wrapper runs `code/evaluate.py --config code/best_config.json`. Every column is an exact match; `amount_safe_to_pay` is also reported within max(1 unit, 1%). Row-exact means all 6 structured columns match (the explanation is not scored).

## Per-column exact matches by phase

| phase | amount | status | method | plan | earliest | changes | row-exact |
|---|---|---|---|---|---|---|---|
| 1 · deterministic engine, dummy decisions | 4 | 8 | 11 | 11 | 9 | 22 | 3 |
| 2 · forecast irregular spending (flag fit) | 4 | 9 | 12 | 12 | **18** | 22 | 3 |
| 3a · image amounts + message rules | 4 | 9 | 12 | 12 | 17 | 22 | 3 |
| 3b · exhaustive plan search | 4 | **19** | **22** | **20** | 17 | 22 | **4** |
| 4 · irregular flexible changes, tests, validator gate | 4 | 19 | 22 | 20 | 17 | 22 | 4 |

Final weighted score (amount 30%, status 25%, earliest 20%, method + plan 20%, changes 5%): **58.60 / 100**. `output.csv` passes the validator.

## What moved each phase

- **Phase 1:** CSV loading, currency conversion, monthly series detection and the 90-day simulation were built behind flags, with dummy decisions.
- **Phase 2:** history stops before the request date, so nothing covered irregular spending (groceries, transport). Projecting it forward (`variable_spending_mode=daily_average`) fixed 8 earliest dates and broke none.
- **Phase 3a:** blank image amounts and message amendments entered the ledger. One earliest date moved away (request_02: an employer raise pulls it a month early). Dropping messages would fix only that row, so the guard kept the spec reading.
- **Phase 3b:** the exhaustive safe-plan search replaced dummy decisions: status +10, method +10, plan +8.
- **Phase 4:** stop / reduce now apply to irregular flexible expenses too, with no sample change. Tests found and fixed an untrusted-message bug, with no output change.

## Known limitation: `amount_safe_to_pay` (4/25, all 4 are rows capped at the request)

1. H0 (reserve pending debits on request_date) changes 0 of 25 amounts. Pending credits and salary timing were verified correct on all 275 ledgers.
2. Residual = my outflow to the low point − the key's implied outflow. It is negative on 19 of 21 wrong rows, at 0.2–14% of balance: the key sees more irregular spending.
3. A subset-sum over ledger items, excluded rows and un-projected groups (≤ 3 items, tolerance 1.0) matches nothing on 15/21 rows. The 6 hits are noise on small EUR/USD residuals.
4. No event type, status, category or source recurs, and 1,878 spending-rule combinations plus 4 alternative horizons never reproduce an amount.
5. request_05 and request_07 (±60% of balance) are income-structure differences. The full table is in `code/DECISIONS.md` (D1, D1b).
