# Interview crib

## Why deterministic instead of letting an LLM decide?
The ground truth was produced by a deterministic script, so the winning system is the one that reproduces rules, not one that reasons fresh each time. A deterministic engine gives the same `output.csv` byte for byte, can be unit-tested, and every recommendation can be traced to a ledger line and a tie-breaker. The model does what only it can do, reading pixels, while the money decisions stay auditable and immune to prompt injection.

## Why exhaustive search instead of heuristics?
The candidate space is tiny: at most four plan types times a few installment options times subsets of up to three spending changes. So I can simulate every candidate and never have to guess. The spec gives a strict six-level ranking, and a single tuple sort key implements it exactly, where a heuristic would silently break a tie-breaker. Exhaustive search moved status from 9 to 19 and method from 12 to 22 on the samples in one step.

## How do you know you didn't overfit 25 samples?
Every ambiguous rule is a named flag with a stated financial meaning, and the fitter adopts a change only if it fixes at least two more rows than it breaks. Across phases it adopted exactly one flag (irregular spending, +8 rows, 0 broken) and rejected four one-row wins as insufficient evidence, all recorded in DECISIONS.md with the request ids each fixed and broke. No request id is hard-coded anywhere, and the validator plus 41 tests check behaviour on synthetic cases the samples never contain.

## Walk through the amount_safe_to_pay failure. What did you rule out?
My amount is too high on most rows, so I tested reserving pending debits immediately (0 of 25 changed), a constant spending-rate multiple, a single missing item, a safety buffer as a fraction of balance or minimum, adding back every excluded event class, and boundary, rounding and off-by-one variants. None held. I then solved for the difference: per-row residuals, a subset-sum over forecast items (no match on 15 of 21 rows), and four alternative horizons (no change). The conclusion is that the key sees 0.2–14% more irregular spending than any rule derivable from history. I froze that column and documented it instead of overfitting.

## How do you handle untrusted images and messages?
They can contribute facts but never instructions: the regex rules extract amounts, dates and percentages, and a fact only enters the ledger if the user's own rows support it, with salary facts accepted only from the employer. Instruction-like text is logged to `blocked_instructions.json` and never executed: the cash-prize "pay the release fee now" scams, and the salary claim embedded in a wallet receipt. A test injects a merchant message demanding payment and claiming a raise, and asserts the forecast doesn't move. That test caught a real bug, which I fixed with no change to the output.

## Why is your cost near zero, and is that a strength or a dodge?
The final run makes zero model calls because the 215 messages are formulaic enough for rules (215/215 coverage), and the 16 images were read once and cached. It's a strength: the pipeline is reproducible, free to re-run and has no injection surface in the decision path. A metered image run is still one command (`extract_images.py`) and would cost about $0.04 on Haiku or $0.18 on Opus. I report the unmetered interactive reads honestly rather than claiming a pipeline I didn't run.

## What would you do with 4 more hours?
First, fit a per-category irregular-spending multiplier directly to the residual table with leave-one-out validation, because the amount column is 30% of the score and the gap is systematic. Second, run the batch image extractor with a key and diff it against the interactive cache, so the token report is fully metered. Third, add rule-family regression tests and model the two unhandled message effects (internal transfers and childcare obligations) once I find rows that support them.
