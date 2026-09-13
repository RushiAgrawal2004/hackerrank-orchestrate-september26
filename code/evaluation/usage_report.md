# Token Usage and Cost Report

## 1. Final full-dataset run (the run that produced `output.csv`)

| model provider | model | model calls | input tokens | output tokens | total tokens | cost |
|---|---|---|---|---|---|---|
| Anthropic | `claude-opus-5` (configured in `code/extract_images.py`; not called: every image was already cached) | 0 | 0 | 0 | 0 | USD 0.00 |
| **overall (all providers and models)** | — | **0** | **0** | **0** | **0** | **USD 0.00** |

No other provider or model is used anywhere in the pipeline. The development-session readings of the 16 images (Anthropic Claude Opus 5 inside Claude Code) happened before this run and are described in section 2.

| metric | value |
|---|---|
| requests processed | 250 |
| total tokens | 0 |
| average tokens per request | 0 |
| estimated total cost | USD 0.00 |
| estimated cost per request | USD 0.00 |
| deterministic | yes: identical `output.csv` on every run (SHA-256 checked) |

**Why zero:** the financial engine is fully deterministic. The ledger, 90-day forecast, message rules, plan search, explanations and validation are plain Python. Model use is confined to reading unstructured input, and that input was read once and cached, so `python3 code/main.py` makes no model calls.

## 2. The 16 image amounts (one-off, unmetered)

- 16 events had blank amounts, each backed by one PNG. They were read with Claude vision in the interactive development session (Claude Code, Claude Opus 5) and cached in `code/image_amounts.json` with `"source": "vision_interactive"`, a confidence and the rule used for ambiguous documents.
- Those readings ran inside the chat session, not through the API, so no per-call token counts exist. This is a one-off of 16 images in total, and it is not part of the pipeline run.
- `code/extract_images.py` is the reproducible batch path:
  - one structured-JSON call per image;
  - cache-first (never re-sends a cached image);
  - token usage appended to `code/token_log.jsonl`.
- It is included and `--dry-run` works, but it was not run: no API key was available in the environment. With the cache complete it would make 0 calls.

### What a metered run would cost (estimate)

Assumptions:
- **Image tokens:** ≈ width × height / 750 after standard resizing (long edge ≤ 1568 px, ≤ ~1.15 MP), from the actual PNG sizes. That gives **20,012 tokens** for the 16 images (24,370 if sent unresized).
- **Text in per call:** ≈ 450 tokens (system prompt, ledger-row context, JSON schema) → 16 × 450 = **7,200**.
- **Output per call:** ≈ 120 tokens of JSON → 16 × 120 = **1,920** (thinking tokens excluded).
- **Totals:** input ≈ 20,012 + 7,200 = **27,212 tokens**, output ≈ **1,920 tokens**.
- **Rates:** per million tokens (input / output), from the published model pricing table (cached 2026-06-24).

| model | rate in / out | input cost | output cost | total (16 images) | per image |
|---|---|---|---|---|---|
| Claude Haiku 4.5 | $1 / $5 | 27,212 × 1 / 1e6 = $0.0272 | 1,920 × 5 / 1e6 = $0.0096 | **$0.037** | $0.0023 |
| Claude Sonnet 5 | $2 / $10 | 27,212 × 2 / 1e6 = $0.0544 | 1,920 × 10 / 1e6 = $0.0192 | **$0.074** | $0.0046 |
| Claude Opus 5 (script default) | $5 / $25 | 27,212 × 5 / 1e6 = $0.1361 | 1,920 × 25 / 1e6 = $0.0480 | **$0.184** | $0.0115 |

- **Upper bound** with unresized images (31,570 input tokens): Haiku $0.041, Sonnet 5 $0.082, Opus 5 $0.206.
- **Thinking allowance:** on Opus 5, adaptive thinking could add ~500 output tokens per call, which is about +$0.20.
- **Per request:** spread over 250 requests, even the Opus figure is under $0.001.

## 3. Messages: 0 tokens

- All 215 messages are parsed by deterministic regex rules in `code/message_rules.py`, in English and Indonesian. Coverage is **215/215**, with none falling through.
- Instruction-like sentences are logged to `code/blocked_instructions.json` and never acted on.
- A prompted approach would need about **250 calls** (one per request with its messages). At about 480 input + 100 output tokens each, that is roughly 120K input / 25K output tokens: ≈ $0.25 on Haiku 4.5, ≈ $0.49 on Sonnet 5 or ≈ $1.23 on Opus 5 per full run.
- A prompted run would also not be byte-reproducible. The rules cost nothing and give the same answer every run.
