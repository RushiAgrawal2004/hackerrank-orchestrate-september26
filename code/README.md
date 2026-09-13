# Buy or Wait? — deterministic affordability engine

For every request in `dataset/requests.csv`, this system decides whether the user can safely pay now, pay through a plan, should wait, or should not proceed. It writes the safe amount, plan, dates, spending changes and an explanation to `output.csv`. **Central idea:** every financial decision is made by deterministic, auditable Python; a model is only ever used to read unstructured input.

**Thesis:** a deterministic financial engine, with model use confined to reading unstructured input (images, messages), an exhaustive safe-plan search, a constraint validator as the final gate, and rules auto-fitted on the samples under an anti-overfit guard.

**Provenance:** `output.csv` is produced entirely by deterministic Python from the `dataset/` files. The only model-derived input is `code/image_amounts.json`: 16 amounts read from receipt images and cached as data. `code/extract_images.py` is provided as the reproducible batch path. The run makes no network and no model calls.

## Run (clone → `output.csv` at the repo root)

```bash
git clone https://github.com/interviewstreet/hackerrank-orchestrate-september26.git
cd hackerrank-orchestrate-september26
python3 -m zipfile -e /path/to/code.zip .   # unpacks code/ and evaluation/ next to dataset/ (overwrites the starter code/)
python3 code/main.py                        # writes ./output.csv (250 rows + header), then runs the validator
python3 code/validate.py                    # PASS / FAIL with offending request_ids
python3 code/evaluation/main.py             # score against dataset/sample_requests.csv
python3 -m pip install pytest               # only needed for the tests
python3 -m pytest code/tests -q             # 41 tests, a few seconds, no network
```

- Requires Python 3.10+; the pipeline uses only the standard library.
- **Windows:** `python3` may be the Microsoft Store stub, so type `python` wherever `python3` appears.
- Paths are resolved from each script's location, so the commands work from any working directory.

## Files

| file | purpose |
|---|---|
| `main.py` | entry point: fitted config → plan per request → root `output.csv` → validator |
| `engine.py` | CSV loading, FX, recurring/irregular detection, 90-day ledger, `simulate`, `max_safe_today`, `earliest_full_date`; every ambiguity is a `CONFIG` flag |
| `message_rules.py` | regex message rules (EN + ID): intent, amount, date, support check, ledger effects, blocked instructions |
| `planner.py` | exhaustive plans × spending-change subsets, eligibility filter, spec tie-breakers as one sort key |
| `explain.py` | template explanations filled with engine numbers |
| `validate.py` | hard output-contract checks, exit 1 on FAIL |
| `evaluate.py` | per-column scorer on the 25 samples |
| `fit_flags.py` | coordinate ascent + top-6 grid over flags; adopts a change only with ≥ 2 net rows |
| `extract_images.py` | reproducible, cached Claude vision batch extraction (not run: no API key) |
| `build_transcript.py` | renders the Claude Code session JSONL into `log.txt` |
| `image_amounts.json` · `best_config.json` · `blocked_instructions.json` | cached image amounts · fitted flags · logged untrusted instructions |
| `tests/` | simulate path, boundary, FX, linked chains, message intents and injection, tie-breakers, validator faults, output contract |
| `evaluation/` | `main.py` scorer wrapper, `results.md`, `usage_report.md` |
| `DATA_NOTES.md` · `DECISIONS.md` · `ARCHITECTURE.md` · `INTERVIEW.md` | data facts · every decision with evidence · design · Q&A |

## Results (25 solved samples, exact match)

| amount | status | method | plan | earliest | changes | row-exact | weighted |
|---|---|---|---|---|---|---|---|
| 4 | 19 | 22 | 20 | 17 | 22 | 4 | 58.6 |

Model calls in the final run: **0** (cost $0.00). Message rule coverage: 215/215.

## Known limitation

- `amount_safe_to_pay` matches exactly on only 4/25 rows, and those are rows capped at the requested amount.
- The key sees 0.2–14% more irregular outflow before the low point than any rule derivable from the history rows. H0–H5, a residual subset-sum and 4 alternative horizons all fail to explain it.
- Evidence: `DECISIONS.md` D1/D1b and `evaluation/results.md`.

## With more time

1. **Fit the irregular-spend rate per category:** estimate it from the residual table (e.g. a multiplier on the recent-30-day spend) with held-out cross-validation over the 25 rows, instead of choosing between discrete flag values.
2. **Run `extract_images.py` with a key:** replace the interactive readings with metered, logged batch output, and diff it against the cache.
3. **Grow the message rules:** add a regression test per rule family, and cover the unmatched effects (internal-transfer pairs, childcare obligations with amounts).
