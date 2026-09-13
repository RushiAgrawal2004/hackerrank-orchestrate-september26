# DATA_NOTES — Buy or Wait? dataset (Phase 1)

All numbers below come from pandas / csv runs over `dataset/`. Nothing is guessed. Where the data does not settle a rule, the rule is a flag in `CONFIG` at the top of `code/engine.py` (see §12).

---

## 0. Inventory

| file | rows (excl. header) | notes |
|---|---|---|
| financial_profiles.csv | 275 | one row per user (25 sample users + 250 request users, disjoint) |
| financial_events.csv | 25,342 | about 6 months of history per user, plus pending/scheduled rows |
| exchange_rates.csv | 134 | dated rates, one direction per pair |
| requests.csv | 250 | `request_26` … `request_275`, one request per user |
| sample_requests.csv | 25 | `request_01` … `request_25`, request columns + 7 solved output columns |
| request_payment_options.csv | 790 | 2–4 options per request |
| messages.csv | 215 | English and Indonesian text (≈41 Indonesian) |
| images.csv | 16 | 16 PNGs in `dataset/media/images/` |
| output.csv | 250 | template: `request_id` filled (same order as requests.csv), other 7 columns blank |

---

## 1. Schemas (exact column names, pandas dtypes, 3 real rows)

### financial_profiles.csv (275)
| column | dtype |
|---|---|
| user_id | object |
| home_currency | object |
| current_available_balance | float64 |
| minimum_balance_to_keep | int64 |
| financial_priorities | object |
| expense_categories_to_protect | object |
| expense_categories_user_is_willing_to_reduce | object |
| expense_categories_user_is_willing_to_stop | object |
| payment_methods_user_will_consider | object |
| max_installment_months | float64 (blank → NaN) |

```
user_01,ZAR,58481.1,18000,education|debt_repayment,rent|education|groceries|debt_repayment,dining,delivery_membership,full_payment,
user_02,IDR,60383889.2,29158400,education|family_support,housing|utilities|education,entertainment,cloud_storage,partial_payment|installments,7
user_03,IDR,5810300,2668700,retirement_investment|emergency_savings,rent|utilities|groceries,streaming|shopping,streaming|cloud_storage,full_payment|partial_payment|installments,2
```

### financial_events.csv (25,342)
| column | dtype |
|---|---|
| event_id | object |
| user_id | object |
| event_type | object |
| description | object |
| category | object |
| direction | object |
| amount | float64 (16 blanks) |
| currency | object |
| event_date | object (YYYY-MM-DD, never blank) |
| settlement_date | object (blank only for the 10 `unrealized` rows) |
| status | object |
| linked_event_id | object (58 non-blank) |
| flexibility | object |
| minimum_allowed_amount | float64 (blank unless reducible) |

```
event_01,user_01,expense,Apartment rent transfer,rent,debit,5148,ZAR,2023-10-02,2023-10-02,settled,,fixed,
event_02,user_01,expense,Household utility payment,utilities,debit,1475.46,ZAR,2023-10-06,2023-10-06,settled,,fixed,
event_03,user_01,expense,Professional training fee,education,debit,1821.6,ZAR,2023-10-08,2023-10-08,settled,,fixed,
```
`event_date` ≠ `settlement_date` on 188 rows (card authorizations, pending and scheduled rows).

### exchange_rates.csv (134)
`rate_date` object, `from_currency` object, `to_currency` object, `rate` float64
```
2023-10-15,EUR,ZAR,20
2023-10-15,USD,EUR,0.92
2023-10-15,USD,IDR,15833.33
```

### requests.csv (250)
`request_id` object, `user_id` object, `request_date` object, `request_type` object, `requested_amount` float64, `desired_completion_date` object, `allows_partial_payment` bool (`true`/`false` lowercase), `request_text` object
```
request_26,user_26,2025-08-03,family_transfer,15656000,2025-10-07,false,"I've been asked to transfer IDR 15,656,000 to my family. I need to complete it by 7 October 2025. Should I send the full amount, send part of it, or wait?"
request_27,user_27,2026-07-05,purchase,6670,2026-08-21,true,"Can I make this purchase without dipping into the balance I want to keep? I need to decide by 21 August 2026. The laptop costs ZAR 6,670."
request_28,user_28,2024-06-07,investment,1302.4,2024-08-15,false,"I'm planning an investment contribution of EUR 1,302.40. What portion can I invest today without going below my minimum balance?"
```

### sample_requests.csv (25)
Same 8 columns as requests.csv, then: `amount_safe_to_pay` float64, `affordability_status`, `recommended_payment_method`, `payment_plan`, `earliest_date_for_full_payment`, `spending_changes_needed`, `decision_explanation` (all object).
```
request_01,user_01,2024-03-03,purchase,25256,2024-03-20,true,"...laptop ... ZAR 25,256.",25256,affordable_now,full_payment,2024-03-03:25256,2024-03-03,none,"Pay ZAR 25,256 today. This leaves at least ZAR 18,000 available over the next 90 days."
request_02,user_02,2025-08-05,travel,46018000,2025-10-10,false,"...IDR 46,018,000...",17229139.2,affordable_with_plan,installments,2025-08-08:15952906.67|2025-09-07:15952906.67|2025-10-07:15952906.67,2025-09-15,none,"Use 3 installments of IDR 15,952,906.67, starting 8 August 2025. This leaves at least IDR 29,158,400 available."
request_03,user_03,2019-09-03,education,5491000,2019-11-15,false,"...IDR 5,491,000.",873000,affordable_later,wait,2019-11-15:5491000,2019-11-15,none,"Pay IDR 5,491,000 in full on 15 November 2019. Paying earlier would take the balance below the IDR 2,668,700 minimum."
```

### request_payment_options.csv (790)
`payment_option_id` object, `request_id` object, `payment_method` object, `payment_amount` float64, `number_of_payments` int64, `first_payment_date` object, `payment_frequency_days` float64 (blank for full_payment), `financing_fee` float64, `total_payable_amount` float64. See §9.

### messages.csv (215)
`message_id`, `user_id`, `request_id` (128 non-blank), `related_event_id` (39 non-blank), `sent_at` (ISO-8601 UTC, e.g. `2025-07-29T09:30:00Z`), `source_type`, `message_text` — all object.
```
message_01,user_02,,,2025-07-29T09:30:00Z,employer,Rincian penggajian Anda di Cobalt Systems telah berubah. Gaji bulanan Anda naik menjadi IDR 42750000. Perubahan ini berlaku mulai 2025-08-15. ...
message_02,user_03,request_03,,2019-08-31T09:30:00Z,employer,Tim payroll BrightPath Media telah mengirim pembaruan. Gaji rutin untuk penggajian berikutnya sudah dikonfirmasi. ...
message_03,user_04,request_04,,2024-06-01T09:30:00Z,employer,Rincian penggajian Anda di Greenfield Foods telah berubah. Bonus kuartalan Anda masih menunggu hasil akhir penilaian kinerja. ...
```

### images.csv (16)
`image_id`, `user_id`, `request_id`, `related_event_id` — all object, all populated.
```
image_01,user_03,request_03,event_253
image_02,user_16,request_16,event_1442
image_03,user_17,request_17,event_1545
```

### output.csv (250)
`request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation`, e.g. `request_26,,,,,,,`

---

## 2. Every categorical value

> There are **no** `is_flexible` / `is_essential` columns. Flexibility is `financial_events.flexibility`. "Essential/protected" comes from `financial_profiles.expense_categories_to_protect`.

### financial_events
- **event_type** (8): expense 20,525 · subscription 2,488 · income 1,696 · debt_payment 567 · investment_purchase 29 · refund 22 · investment_valuation 10 · investment_sale 5
- **category** (22): groceries 5,812 · transport 5,626 · dining 3,479 · salary 1,690 · utilities 1,452 · rent 1,355 · cloud_storage 833 · shopping 813 · streaming 683 · debt_repayment 553 · entertainment 521 · insurance 456 · music_subscription 451 · healthcare 356 · delivery_membership 351 · education 306 · housing 246 · gym 170 · family_support 125 · investment 44 · work_expense 14 · windfall 6
- **direction** (3): debit 23,609 · credit 1,723 · non_cash 10
- **currency** (5): INR 6,457 · EUR 5,585 · IDR 4,992 · ZAR 4,489 · USD 3,819
- **status** (6): settled 25,148 · pending 71 · scheduled 70 · cancelled 22 · failed 21 · unrealized 10
- **flexibility** (4): fixed 21,138 · reducible 2,682 · stoppable 1,297 · reducible_or_stoppable 225
- **minimum_allowed_amount**: filled exactly when flexibility ∈ {reducible, reducible_or_stoppable} (2,907 rows). Blank for fixed and stoppable.

event_type × status:

| event_type | settled | pending | scheduled | failed | cancelled | unrealized |
|---|---|---|---|---|---|---|
| expense | 20,410 | 63 | 16 | 14 | 22 | 0 |
| subscription | 2,488 | 0 | 0 | 0 | 0 | 0 |
| income | 1,649 | 0 | 47 | 0 | 0 | 0 |
| debt_payment | 553 | 0 | 7 | 7 | 0 | 0 |
| investment_purchase | 29 | 0 | 0 | 0 | 0 | 0 |
| refund | 14 | 8 | 0 | 0 | 0 | 0 |
| investment_valuation | 0 | 0 | 0 | 0 | 0 | 10 |
| investment_sale | 5 | 0 | 0 | 0 | 0 | 0 |

flexibility × event_type: stoppable (1,297) and reducible_or_stoppable (225) are **all** `subscription`. reducible: 2,505 expense + 177 subscription. Every income/debt/refund/investment row is `fixed`.

Descriptions of non-settled rows:
- **pending debits:** "Pending fuel authorization", "Pending merchant debit", "Pending pharmacy card charge", "Pending online order charge", "Possible duplicate card charge" (6), "Outstanding telecom bill" (blank amount), "Large grocery tax invoice" (blank amount)
- **pending credits:** "Pending merchant refund" (8)
- **scheduled debits:** "Scheduled school fee", "Scheduled insurance payment", "Scheduled utility debit", "Scheduled bill payment retry" (debt_payment), "Outstanding rent balance" (blank), "Hospital bill payable" (blank)
- **scheduled credits:** "Next confirmed salary" (47)
- **failed:** "Failed utility debit", "Failed subscription debit", "Failed card payment", "Failed bill payment attempt"
- **cancelled:** "Card authorization" (8, each followed by a settled purchase), "Cancelled card authorization", "Cancelled merchant authorization", "Cancelled booking authorization"

Timing (checked against each user's request_date):
- 0 settled rows are dated on or after request_date.
- All 71 pending rows and the 23 non-salary scheduled rows have `event_date ≤ request_date < settlement_date`.
- All 47 scheduled salaries fall entirely after request_date.

So `current_available_balance` is consistent with "all settled rows already applied".

### financial_profiles
- **home_currency**: INR 67 · EUR 62 · IDR 55 · ZAR 51 · USD 40
- **financial_priorities** (always 2 tokens): debt_repayment, education, emergency_savings, family_support, healthcare, housing, retirement_investment, travel
- **expense_categories_to_protect** (3–4 tokens): debt_repayment, education, family_support, groceries, healthcare, housing, insurance, rent, transport, utilities
- **expense_categories_user_is_willing_to_reduce** (0–3 tokens; blank for 39 users): dining, entertainment, gym, shopping, streaming
- **expense_categories_user_is_willing_to_stop** (0–3 tokens; blank for 62 users): cloud_storage, delivery_membership, gym, music_subscription, streaming
- **payment_methods_user_will_consider** (7 combos): full_payment 60 · partial_payment|installments 52 · installments 41 · full_payment|partial_payment 40 · full_payment|installments 35 · full_payment|partial_payment|installments 28 · partial_payment 19
- **max_installment_months**: blank 119 · 2:15 · 3:18 · 4:17 · 5:16 · 6:13 · 7:14 · 8:10 · 9:9 · 10:12 · 11:16 · 12:16. Blank **exactly** when `installments` is not in payment_methods (119/119 and 156/156).

### requests / sample_requests
- **request_type** (9): purchase, travel, education, family_transfer, debt_repayment, investment, housing (28 each in requests); emergency_expense, other (27 each). Samples: 3 each, except emergency_expense and other with 2.
- **allows_partial_payment**: requests false 170 / true 80; samples false 13 / true 12.
- **sample affordability_status**: affordable_with_plan 9 · not_affordable 7 · affordable_later 6 · affordable_now 3
- **sample recommended_payment_method**: not_recommended 7 · full_payment 6 · wait 6 · installments 5 · partial_payment 1
- **sample spending_changes_needed**: none 22 · `stop:event_476` · `reduce_to:event_989:665950` · `stop:event_1815|reduce_to:event_1816:23.50`

### request_payment_options
- **payment_method**: installments 515 · full_payment 275
- **number_of_payments**: 1 (275) · 24 (96) · 15 (89) · 21 (88) · 18 (87) · 3 (80) · 6 (65) · 2 (7) · 4 (3)
- **payment_frequency_days**: blank 275 (all full_payment) · 28 (180) · 31 (169) · 30 (166)
- **options per request**: 2 → 65 requests · 3 → 180 · 4 → 30

### messages
- **source_type**: employer 126 · service_provider 31 · financial_service 23 · bank 18 · merchant 17

---

## 3. How recurring expenses are encoded

**There is no frequency, interval, or day-of-month column in financial_events.** Recurrence exists only as **repeated rows**: one row per month with the same `event_type` + `description` + `category`, the same day of month, 30–31 days apart. The only explicit interval anywhere is `request_payment_options.payment_frequency_days`.

Evidence (settled rows grouped by user + event_type + description + category):
- **1,830 series** have one identical day of month and 5–6 rows (1,538 with n=5, 292 with n=6). Median gap: 30.5 or 31 days (1,831 of 1,877 series with n ≥ 3). Categories: rent, utilities, insurance, housing, healthcare, education, family_support, entertainment, shopping, debt_repayment, all subscription categories, salary.
- **Variable spending** (groceries, transport, dining) uses rotating descriptions ("Neighbourhood grocer", "Commuter pass", "Takeaway order", …) on random days, roughly weekly. Series with n ≥ 3 and several days of month: groceries 1,081, transport 993, dining 518. These are not monthly bills.
- **Amounts:** rent and subscriptions are constant. Utilities, healthcare, entertainment and shopping vary monthly (user_01 utilities 1,386.17–1,651.81).
- **History** ends 1–3 days before request_date. Nothing dated on request_date exists, so a bill due on request_date appears in no row (user_06 rent is on day 3, request_date is 2026-01-03).
- **Flexible series:** stoppable and reducible_or_stoppable rows form monthly subscription series (n=5/6). Reducible rows split into 149 monthly series (e.g. "Cinema and events") and ~940 irregular dining series of 1–7 rows.
- **Sample spending changes:**
  - `event_476` is the **latest** row of "Family streaming plan" (event_444 … event_476).
  - `event_1815` and `event_1816` are the latest rows of their series.
  - `event_989` ("Weekend food delivery", reducible) is the latest of only **2** irregular rows (2024-12-18, 2025-04-23). So the ground truth treats at least some irregular reducible dining as changeable.
  - Both sample `reduce_to` amounts equal `minimum_allowed_amount` (event_989 min 665950 → 665950; event_1816 min 23.5 → 23.50).

---

## 4. How the next salary is encoded

Two encodings:

1. **One explicit row** (47 users): `event_type=income`, `category=salary`, `description="Next confirmed salary"`, `status=scheduled`, `event_date = settlement_date` > request_date. These are the only scheduled income rows. 8 are in a foreign currency (user_25, 39, 41, 63, 79, 109, 260 USD; user_257 EUR).
   Example user_01: history has only `Prorated first salary` 12,826 on 2024-02-15, then `Next confirmed salary` 23,320 on 2024-03-15 (request 2024-03-03).
2. **No future row** (228 users): only a monthly settled history, mostly day 15 (1,162 of 1,696 income rows fall on day 15).
   Sample request_02 (user_02, no scheduled row, last payroll 2025-07-15) has expected `earliest_date_for_full_payment = 2025-09-15`. Future salary must therefore be **projected from history**, not taken only from explicit rows. message_01 also raises user_02 pay to IDR 42,750,000 from 2025-08-15.

**Income is not all salary-like:**
- **Gig payouts:** "Delivery platform payout", "Driver platform payout", "Weekly app earnings", "Task marketplace payout" (weekly, days 4/5, 11/12, 18/19, 25/26)
- **Freelance invoices:** days 8 and 20–22
- **Commissions:** day 24
- **One-offs:** "Quarterly performance bonus" (day 22), "Promotion arrears payment" (day 20), "Prize proceeds" (windfall, 6)
- **Series that stopped:**
  - "Previous employer payroll" and "Second household income" end ~45–54 days before request_date.
  - Seasonal pay ("Peak-season wages", "Seasonal contract payment", "Temporary assignment pay") ends 78–84 days before request_date for 9 users (user_12, 29, 61, 133, 201, 213, 237, 241, 265).

**Salary-related messages:** raises, temporary cuts, unpaid-leave reductions, pay-date moves ("now expected on 2024-09-23"), first-salary confirmations, contract ended, commission not approved, bonus pending. All are Phase 2 (LLM) inputs.

---

## 5. Blank amounts — 16 events, each mapped to exactly one image

| event_id | user | status | cash date | request_date | timing | description / category | currency | image_id | request |
|---|---|---|---|---|---|---|---|---|---|
| event_253 | user_03 | settled | 2019-08-31 | 2019-09-03 | historical | August 2019 net salary / salary (income) | IDR | image_01 | request_03 (sample) |
| event_1442 | user_16 | scheduled | 2023-08-16 | 2023-08-12 | **future** | Outstanding rent balance / rent | INR | image_02 | request_16 (sample) |
| event_1545 | user_17 | settled | 2026-02-27 | 2026-03-01 | historical | Bulk groceries and pantry purchase / groceries | INR | image_03 | request_17 (sample) |
| event_1700 | user_19 | settled | 2024-09-03 | 2024-09-04 | historical | Delivered grocery order / groceries | INR | image_04 | request_19 (sample) |
| event_1786 | user_20 | pending | 2026-02-09 | 2026-02-07 | **future** | Outstanding telecom bill / utilities | INR | image_05 | request_20 (sample) |
| event_3051 | user_33 | settled | 2026-01-06 | 2026-01-07 | historical | Grocery tax invoice / groceries | INR | image_06 | request_33 |
| event_3231 | user_35 | settled | 2025-10-29 | 2025-10-30 | historical | Restaurant tax invoice / dining | INR | image_07 | request_35 |
| event_4535 | user_48 | settled | 2026-07-24 | 2026-07-25 | historical | Property maintenance invoice / housing | INR | image_08 | request_48 |
| event_5170 | user_55 | settled | 2026-06-07 | 2026-06-08 | historical | Water bill due / utilities | INR | image_09 | request_55 |
| event_6033 | user_64 | pending | 2024-06-10 | 2024-06-04 | **future** | Large grocery tax invoice / groceries | INR | image_10 | request_64 |
| event_6859 | user_73 | scheduled | 2023-01-23 | 2023-01-20 | **future** | Hospital bill payable / healthcare | INR | image_11 | request_73 |
| event_7307 | user_78 | settled | 2025-10-01 | 2025-10-02 | historical | Taxi fare / transport | **USD** (home INR) | image_12 | request_78 |
| event_7941 | user_84 | settled | 2026-04-03 | 2026-04-04 | historical | Tote bag order / shopping | INR | image_13 | request_84 |
| event_9421 | user_101 | settled | 2025-11-02 | 2025-11-03 | historical | Pharmacy purchase / healthcare | INR | image_14 | request_101 |
| event_9806 | user_105 | settled | 2026-06-07 | 2026-06-08 | historical | Airline ticket purchase / transport | INR | image_15 | request_105 |
| event_10521 | user_113 | settled | 2026-09-03 | 2026-09-04 | historical | EV charging wallet payment / transport | INR | image_16 | request_113 |

- **4 blanks are future cash movements** (event_1442, event_1786, event_6033, event_6859). They directly change the forecast.
- **event_253 is historical, but it is a salary row**, so its amount may set the projected salary level for user_03.
- Messages on blank events:
  - message_35 (event_4535): the receipt carries the final amount and the original due date.
  - message_64 (event_7941).
  - message_86 (event_10521): also claims "employer has confirmed a USD 1296 salary credit for 15 September 2026". That is unsupported extra income inside a receipt message and must be treated as untrusted.
- The engine never uses 0. Amounts come from `code/image_amounts.json` (`{event_id: amount_in_event_currency}`), to be filled by the image reader in Phase 2. Until then those rows are excluded with a warning.

---

## 6. linked_event_id chains

- 58 links. **Every chain has exactly 2 events** (parent → child), no parent has two children, and the child is the later lifecycle step.
- The link alone does not decide cash treatment. The child's `status` does.

| # | pattern (parent → child) | count | meaning |
|---|---|---|---|
| 1 | expense/settled → refund/settled (credit) | 14 | card charge reversed, or reimbursable work expense → employer reimbursement. Both settled, so already in the balance |
| 2 | expense/**cancelled** "Card authorization" → expense/settled "Settled card purchase" | 8 | authorization replaced by settlement (amendment). Count once |
| 3 | expense/settled → refund/**pending** "Pending merchant refund" | 8 | refund initiated, not received. Pending credit, ignore |
| 4 | investment_purchase/settled → investment_valuation/**unrealized** (non_cash) | 10 | market value only, not cash |
| 5 | debt_payment/**failed** → debt_payment/**scheduled** "Scheduled bill payment retry" | 7 | bill still owed. Ignore the failed row, count the retry as a future debit |
| 6 | investment_purchase/settled → investment_sale/settled (credit) | 5 | realized sale proceeds (historical) |
| 7 | expense/settled "Original card charge" → expense/**pending** "Possible duplicate card charge", same amount | 6 | duplicate under dispute, reversal not posted |

Three full chains:

**A — amendment (authorization superseded by settlement), user_01**
```
event_100,user_01,expense,Card authorization,shopping,debit,816.2,ZAR,2024-02-14,2024-02-16,cancelled,,fixed,
event_101,user_01,expense,Settled card purchase,shopping,debit,816.2,ZAR,2024-02-16,2024-02-17,settled,event_100,fixed,
```
The authorization was cancelled because it turned into the settled purchase. Cash moved once (816.20), and it is historical.

**B — failed payment + scheduled retry (still owed), user_91**
```
event_8575,user_91,debt_payment,Failed bill payment attempt,utilities,debit,166,EUR,2024-09-01,2024-09-01,failed,,fixed,
event_8576,user_91,debt_payment,Scheduled bill payment retry,utilities,debit,166,EUR,2024-09-03,2024-09-07,scheduled,event_8575,fixed,
```
message_69: "The previous debit attempt failed. The bill is still outstanding and another debit will be attempted." Request date 2024-09-03, so EUR 166 is a future debit on 2024-09-07.

**C — possible duplicate, user_138**
```
event_12708,user_138,expense,Original card charge,shopping,debit,134.75,EUR,2026-03-26,2026-03-27,settled,,fixed,
event_12709,user_138,expense,Possible duplicate card charge,shopping,debit,134.75,EUR,2026-04-06,2026-04-10,pending,event_12708,fixed,
```
message_106: "The extra card charge is still being investigated. A reversal has not been posted." Either a duplicate record (ignore) or a real pending debit (safer to reserve) → flag `possible_duplicate_pending_debit`.

Also: `event_98` "Card charge later reversed" (583) → `event_99` "Settled card charge reversal" (+583, settled) is a refund. `event_1855` investment 676.80 → `event_1856` valuation 270.72 is non_cash/unrealized.

---

## 7. Currencies

- Home currency per user is in §2. Balances, minimums, requests and payment options are in home currency.
- **140 event rows across 27 users use a non-home currency:**
  - 139 are income: 131 settled payroll plus 8 scheduled "Next confirmed salary".
  - 1 is an expense: event_7307, a blank USD taxi fare (user_78, home INR).

| home → event currency | users (row count) |
|---|---|
| INR ← USD | user_39 (6), user_48 (6), user_63 (6), user_64 (5), user_78 (1), user_84 (5), user_113 (5), user_173 (5), user_184 (5), user_214 (5), user_245 (5) |
| IDR ← USD | user_25 (6), user_41 (6), user_71 (5), user_183 (5), user_260 (6) |
| EUR ← USD | user_79 (6), user_109 (6), user_267 (5), user_274 (5) |
| ZAR ← EUR | user_98 (5), user_125 (5), user_169 (5), user_263 (5) |
| USD ← EUR | user_153 (5), user_235 (5), user_257 (6) |

**Exchange rates:**
- All 140 rows have a **direct** `from_currency=event currency → to_currency=home` rate on their settlement_date. None needs an inverse or a fallback.
- Each pair has one constant rate: EUR→USD 1.09, EUR→ZAR 20, USD→EUR 0.92, USD→IDR 15833.33, USD→INR 83.33.
- Rates are dated the 15th monthly, plus one USD→INR row on 2025-10-01 (matches event_7307).
- Some pair/month rows are missing (e.g. no USD→EUR 2025-03-15 … 2025-07-15; no EUR→ZAR 2024-06-15 … 2024-11-15). A **projected** foreign salary can land on a date with no rate → flag `fx_missing_rate`. The rates are constant, so the fallback does not change values.

---

## 8. Multi-value fields and formats

- **Separator `|`**, no spaces, lowercase snake_case tokens, never quoted. An empty string means an empty list.
- `payment_methods_user_will_consider`: tokens always appear in the order full_payment → partial_payment → installments (7 combos in §2).
- `financial_priorities`: 2 tokens. `expense_categories_to_protect`: 3–4 tokens. Reduce and stop lists: 0–3 tokens.
- `allows_partial_payment`: `true` / `false`.
- **Output formats (from samples):**
  - `payment_plan`: `YYYY-MM-DD:amount|…`
  - `spending_changes_needed`: `stop:event_x|reduce_to:event_y:amount`
  - Amounts inside `payment_plan` / `reduce_to` are written as integers when whole (`25256`, `665950`), otherwise with 2 decimals (`620.40`, `996.60`, `23.50`).
  - `amount_safe_to_pay` is written as a shortest float (`603.3`, `17229139.2`, `87170.56`). Every sample value has ≤ 2 decimals.
  - `earliest_date_for_full_payment` is empty when never.
- `messages.sent_at`: `YYYY-MM-DDTHH:MM:SSZ`.

---

## 9. request_payment_options.csv

| column | meaning |
|---|---|
| payment_option_id | unique id, `payment_option_NN`. Lowest id is the final tie-breaker |
| request_id | request the offer belongs to |
| payment_method | `full_payment` or `installments` (there is never a partial_payment option) |
| payment_amount | amount of each payment (home currency) |
| number_of_payments | count of equal payments |
| first_payment_date | date of payment #1 |
| payment_frequency_days | days between payments (blank for full_payment) |
| financing_fee | explicit fee on top of requested_amount |
| total_payable_amount | sum of all payments |

Invariants verified on all 790 rows:
- **Exactly one `full_payment` per request** (275/275): `number_of_payments=1`, `first_payment_date == request_date`, `payment_amount == requested_amount`, fee 0.
- **Installments** (515):
  - `payment_amount × number_of_payments == total_payable_amount` exactly.
  - `total_payable_amount − requested_amount − financing_fee == 0` exactly.
  - First payment is request_date + {0 d: 106, 1: 2, 3: 156, 5: 2, 6: 1, 7: 104, 14: 144}.
- **Schedule:** payment k is on `first_payment_date + k × payment_frequency_days`. Verified against the sample plans:
  - request_02 = option_05: 08-08, +30 → 09-07, +30 → 10-07.
  - request_07 = option_19: 28 days → 09-12, 10-10, 11-07.

Three real rows in words:
```
payment_option_01,request_01,full_payment,25256,1,2024-03-03,,0,25256
payment_option_02,request_01,installments,1852.11,15,2024-03-06,30,2525.65,27781.65
payment_option_03,request_01,installments,4546.08,6,2024-03-10,31,2020.48,27276.48
```
- **option_01:** pay the whole ZAR 25,256 once, on the request date (2024-03-03), with no fee.
- **option_02:** 15 payments of ZAR 1,852.11, the first on 2024-03-06 and then every 30 days (last on 2025-04-26). ZAR 2,525.65 financing fee, ZAR 27,781.65 in total.
- **option_03:** 6 payments of ZAR 4,546.08, the first on 2024-03-10 and then every 31 days. ZAR 2,020.48 fee, ZAR 27,276.48 in total.

---

## 10. Request counts

- **requests.csv: 250** (`request_26` … `request_275`). **sample_requests.csv: 25** (`request_01` … `request_25`).
- One request per user. The two user sets are disjoint.
- `dataset/output.csv` lists the same 250 ids in the same order as requests.csv.

---

## 11. Other facts that matter for the rules

- There are no exact duplicate rows (same user + description + amount + date + direction = 0). "Duplicate records" appear instead as:
  - chain pattern 7 ("Possible duplicate card charge");
  - bank messages saying a matching debit and credit were a transfer between the user's own accounts (message_13 user_18, message_23 user_33).
- Messages with `related_event_id` (39) cover: pending refunds, unrealized valuations, prize proceeds settled, failed bill + retry, possible duplicates, reimbursements, investment sale proceeds, and the 3 blank-amount receipts.
- Profile/request messages without an event (e.g. salary raise, new childcare payment "begins in the same month" for user_14, lease increases rent by 12% for user_16) add or amend **recurring** items. Phase 2.
- **Phase 1 harness signal:** with defaults, engine `amount_safe_to_pay` is **too high** on 20 of 21 misses (only request_07 is too low). `earliest_date_for_full_payment` is exactly **one month early** on 4 rows (request_03, 18, 22, 23). The forecast is missing outflows.
- **Flag sweep:** `variable_spending_mode=daily_average` with `variable_spending_categories=protected` raises earliest-date accuracy from 9/25 to **17/25**. With `all`: 16/25. This is the first lead for Phase 2.

---

## 12. CONFIG flags (code/engine.py)

| flag | default | interpretation A | interpretation B (/ C) |
|---|---|---|---|
| `horizon_days` | 90 | forecast length in days | — |
| `forecast_starts_day_0_or_1` | 0 | 0: items dated request_date (e.g. rent due that day, no row yet) hit the balance on day 0 | 1: request_date items already reflected in balance; walk items from request_date+1 |
| `forecast_includes_day_90` | True | window = request_date … request_date+90 inclusive (91 days). Earliest-date search also runs to +90 | window ends at +89 (exactly 90 days) |
| `earliest_date_window_anchor` | request_date | the safety window always ends request_date+90 | re-anchor: paying on day d must be safe through d+90 |
| `salary_applied_before_expenses_same_day` | True | credits applied before debits on the same day | debits first (a payday bill can breach before salary lands) |
| `min_balance_checked_after_payment` | True | check the balance after **every** movement (intraday low) | check only the end-of-day balance |
| `check_opening_balance` | True | opening balance below the minimum → nothing is safe | only check forward movements |
| `unsafe_if_equal_to_minimum` | False | balance == minimum is safe ("never falls below") | must stay strictly above |
| `rounding_mode` | floor_2dp | floor to cents (safe side) | round_2dp / floor_int / round_int |
| `binary_search_precision` | 0.0005 | search tolerance before rounding (technical) | — |
| `amount_format` | int_if_whole_else_2dp | `25256`, `620.40` (matches sample plans) | always 2 decimals |
| `fx_date_field` | settlement_date | convert with the rate on settlement_date (AGENTS.md) | rate on event_date |
| `fx_allow_inverse` | True | use 1/rate if only the reverse pair exists | direct pair only |
| `fx_missing_rate` | nearest_prior | latest rate on or before the date | nearest date either side / error |
| `fx_round_2dp` | True | round converted amounts to cents | keep full precision |
| `include_pending_debits` | True | reserve pending debits | ignore them |
| `pending_debit_date` | settlement_date | pending debit hits on its settlement_date | reserve immediately on request_date |
| `include_pending_credits` | False | ignore pending refunds/credits (spec) | count them |
| `include_scheduled_debits` | True | count scheduled bills / retries | ignore |
| `include_scheduled_credits` | True | count "Next confirmed salary" | ignore |
| `possible_duplicate_pending_debit` | include | pending same-amount child of a settled charge is still reserved (safer; dispute open) | exclude as a duplicate record |
| `linked_resolution` | child_supersedes_parent | a parent with a child is dropped from series detection and the forward ledger | ignore links; status alone decides |
| `blank_amount_policy` | override_else_skip | use `image_amounts.json`, else exclude the row with a warning (never 0) | raise an error if the override is missing |
| `recurring_expense_event_types` | expense, subscription, debt_payment | event types eligible as recurring debits | — |
| `recurring_min_occurrences` | 3 | debit series needs ≥ 3 rows | 2 / 5 … |
| `recurring_min_occurrences_income` | 2 | income series needs ≥ 2 rows (catches prorated + next confirmed) | 3+ |
| `recurring_max_dom_spread` | 0 | identical day of month required | allow ±N days |
| `recurring_require_one_per_month` | True | at most one row per calendar month | allow several |
| `recurring_max_staleness_days` | 35 | series is over if the last row is > 35 days before request_date (catches seasonal / previous employer) | larger or smaller |
| `recurring_amount_basis` | last | project the latest amount | mean / max (conservative for variable bills) |
| `recurring_day_basis` | mode | most common day of month | last row's day |
| `recurring_include_income` | True | project salary monthly beyond history (needed for request_02) | only explicit scheduled salary rows ("don't invent income") |
| `income_series_key` | category_dom | income grouped by category + payday (merges "Prorated first salary", "Payroll credit", "Next confirmed salary") | grouped by description |
| `income_projection_categories` | [salary] | only salary income is projected | include windfall etc. |
| `income_exclude_keywords` | commission, bonus, arrears, prize, reimbursement | never project these | project everything in the category |
| `dedupe_projection_against_explicit` | credits_only | skip a projected credit if an explicit credit of the same category is within N days | all (debits too, e.g. "Scheduled utility debit" vs projected utility) / off |
| `dedupe_window_days` | 7 | window for the dedupe above | — |
| `variable_spending_mode` | none | forecast only recurring + explicit rows | daily_average: spread irregular spending evenly per day |
| `variable_spending_categories` | protected | variable spend counted only in the user's protected categories ("essential") | all debit categories |
| `variable_spending_lookback_days` | 90 | history window for the daily average | 30 / 180 … |
| `spending_change_event_ref` | any_occurrence | any row id in a series maps to that series | only the latest row id (what samples use) |
| `reduce_to_uses_minimum_cut` | True | reduce_to amount = `minimum_allowed_amount` (both samples) | reduce_to_zero |

### Phase 2 flags (forecast outflows, salary projection)

| flag | default | interpretation A | interpretation B (/ C / D) |
|---|---|---|---|
| `variable_spending_mode` | none (fit adopted **daily_average**) | no irregular spending after request_date | daily_average: per-category rate from history spread per day / replay_last_period: re-play the actual rows of the last lookback period shifted forward / monthly_total_spread: a monthly total per calendar month |
| `variable_lookback_days` | 90 | history window for the rate | 30 / 60 / all_history |
| `variable_window_anchor` | request_date | window ends on request_date | window ends on the user's last settled row (history stops 1–3 days early) |
| `variable_spending_categories` | protected_only | only the profile's protected categories ("essential") | all / all_except_flexible (drops reducible dining) |
| `variable_average_basis` | mean | total ÷ window length | median of 30-day block totals |
| `variable_applied_as` | even_daily_amount | same amount every day | same_weekday_pattern / same_day_of_month_pattern (history's shape) |
| `project_recurring_from` | request_date | skip monthly occurrences that fall between the last row and the forecast start | last_row_date: catch them up on day 0. **Inert on this data: 0 of 1,867 series have such an occurrence** |
| `salary_projection_amount` | last_occurrence | latest payroll amount (includes "Next confirmed salary") | median_of_last_n / mean_of_last_n |
| `salary_projection_n` | 3 | n for the median/mean | 6 / all |
| `salary_projection_day` | same_day_of_month | payday = modal day of month | same_interval: last date + median gap |
| `stopped_income_cutoff_days` | 35 | income series with no row for > 35 days is over (seasonal, previous employer, second household income) | 20 / 45 / 62 |
| `project_irregular_income` | False | commission, bonus, arrears, prize, gig payout, freelance invoice, seasonal pay are never projected (`irregular_income_keywords`) | project them like salary |
| `use_fast_path` | True | one no-payment walk gives `max_safe_today` and `earliest_full_date` (verified identical to binary search / 91-day loop on 25/25 samples under 5 configs) | slow reference implementations |

Phase 2 findings:
- Irregular spending is the missing outflow. Across the 21 samples with `amount_safe_to_pay < requested_amount`, the implied extra outflow before the low point is about 0.7–1.3× the all-category 30-day average on 15 rows. The spread is too wide for any tested rule (1,878 combinations) to reproduce an amount exactly: best 0/21 exact, 4/21 within tolerance. The key probably uses generator-internal spending parameters, not a function of the history rows.
- The other 6 rows (request_05, 07, 08, 13, 18, 20) are off by far more than spending can explain. All but request_05 and request_13 have messages; those two have none, so something else (income detection?) is involved there too.

**Ambiguities not yet flagged (Phase 2 planner):**
- whether `max_installment_months` compares to `number_of_payments` or to the schedule's calendar span;
- how irregular reducible dining becomes a changeable recurring expense (event_989);
- "minimum total paid" ranking with financing fees;
- how messages amend recurring amounts and dates;
- whether `spending_changes` affect `earliest_date_for_full_payment` (the spec says no).
