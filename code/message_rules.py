"""Deterministic message rules (no LLM).

    python code/message_rules.py     # print every non-irrelevant claim with its matched span, coverage,
                                     # and write code/blocked_instructions.json

Messages are untrusted data. Regex rules extract facts (amounts, dates, percentages). Instruction-like sentences are
logged to blocked_instructions.json and never acted on. A claim changes the ledger only when the user's own event rows
support it: unsupported income never enters the ledger; unsupported expenses follow unsupported_expense_policy.
Effects are applied by engine.build_ledger after linked_event_id resolution.
"""
from __future__ import annotations

import dataclasses
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
BLOCKED_PATH = CODE_DIR / "blocked_instructions.json"

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
MONEY = r"(?P<cur>IDR|INR|ZAR|USD|EUR)\s?(?P<num>\d[\d,]*(?:\.\d+)?)"
ISO = r"(?P<date>\d{4}-\d{2}-\d{2})"
LONG = r"(?P<long>\d{1,2} (?:" + MONTHS + r") \d{4})"


@dataclass(frozen=True)
class Rule:
    name: str
    intent: str      # cancel | amend_amount | delay | confirm | new_obligation | new_income | irrelevant
    subject: str     # what the claim is about; drives the support check
    status: str      # confirmed | pending | ended | settled | announced | claimed | info
    pattern: re.Pattern
    date_pattern: re.Pattern | None = None


def _rule(name, intent, subject, status, pattern, date_pattern=None) -> Rule:
    return Rule(name, intent, subject, status, re.compile(pattern, re.I),
                re.compile(date_pattern, re.I) if date_pattern else None)


RULES = [
    _rule("salary_increase", "amend_amount", "income", "confirmed",
          r"(?:monthly salary has increased to|gaji bulanan anda naik menjadi)\s+" + MONEY,
          r"(?:change applies from|berlaku mulai)\s+" + ISO),
    _rule("temporary_pay", "amend_amount", "income", "confirmed",
          r"(?:temporary monthly pay is|gaji bulanan sementara anda adalah)\s+" + MONEY),
    _rule("reduced_next_salary", "amend_amount", "income", "confirmed", r"(?:next salary is reduced to)\s+" + MONEY),
    _rule("regular_salary_next_payroll", "amend_amount", "income", "confirmed",
          r"(?:regular salary for the next payroll is|gaji rutin anda untuk penggajian berikutnya adalah)\s+" + MONEY),
    _rule("one_time_arrears", "new_income", "income_one_off", "confirmed",
          r"(?:one-time arrears adjustment of|penyesuaian tunggakan satu kali sebesar)\s+" + MONEY),
    _rule("regular_salary_confirmed", "confirm", "income", "confirmed", r"gaji rutin untuk penggajian berikutnya sudah dikonfirmasi"),
    _rule("salary_date_moved", "delay", "income", "confirmed",
          r"(?:confirmed salary is now expected on|gaji yang sudah dikonfirmasi kini diperkirakan masuk pada)\s+" + ISO),
    _rule("first_salary", "new_income", "income_new", "confirmed",
          r"(?:first salary (?:will be|of|from the new employer is)|gaji pertama (?:dari perusahaan baru adalah|anda sebesar))\s+" + MONEY,
          r"(?:confirmed credit date is|is scheduled for|it is confirmed for|dikonfirmasi untuk|dijadwalkan pada|"
          r"tanggal kredit yang dikonfirmasi adalah)\s+" + ISO),
    _rule("salary_confirmed_for_date", "confirm", "income", "confirmed",
          r"(?:your salary of|gaji sebesar)\s+" + MONEY + r"\s+(?:is confirmed for|dikonfirmasi untuk)\s+" + ISO),
    _rule("salary_resumes", "new_income", "income_resume", "confirmed", r"regular salary of\s+" + MONEY + r"\s+resumes on\s+" + ISO),
    _rule("new_childcare_obligation", "new_obligation", "expense_new", "announced", r"new recurring childcare payment begins"),
    _rule("household_income_ended", "cancel", "income_partial_end", "ended",
          r"(?:one household employment record has ended|salah satu sumber pendapatan kerja rumah tangga telah berakhir)"),
    _rule("remaining_salary", "amend_amount", "income_remaining", "confirmed",
          r"(?:remaining confirmed monthly salary is|sisa gaji bulanan yang dikonfirmasi adalah)\s+" + MONEY),
    _rule("seasonal_contract_ended", "cancel", "income_end", "ended",
          r"(?:current seasonal contract has ended|kontrak musiman saat ini telah berakhir)"),
    _rule("employment_ended", "cancel", "income_end", "ended", r"(?:your employment has ended|hubungan kerja anda telah berakhir)"),
    _rule("base_salary_confirmed", "confirm", "income_base", "confirmed",
          r"(?:confirmed base salary is|gaji pokok yang dikonfirmasi adalah)\s+" + MONEY),
    _rule("commission_pending", "new_income", "income_pending", "pending",
          r"(?:commission shown for open deals is still pending|komisi dari transaksi yang masih berjalan belum disetujui)"),
    _rule("bonus_pending", "new_income", "income_pending", "pending",
          r"(?:quarterly bonus is still subject to|bonus kuartalan anda masih menunggu)"),
    _rule("gig_payout_pending", "new_income", "income_pending", "pending",
          r"(?:payout is still pending|pembayaran berikutnya dari \S+ masih tertunda)"),
    _rule("invoice_approved", "new_income", "income_new", "confirmed",
          r"(?:client approved an invoice payment of|klien menyetujui pembayaran faktur sebesar)\s+" + MONEY,
          r"(?:settlement is expected on|penyelesaian diperkirakan pada)\s+" + ISO),
    _rule("rent_increase", "amend_amount", "rent", "confirmed",
          r"(?:renewed lease increases monthly rent by|perpanjangan sewa menaikkan biaya sewa bulanan sebesar)\s+(?P<pct>\d+(?:\.\d+)?)\s?%"),
    _rule("internal_transfer", "cancel", "transfer", "settled",
          r"(?:matching debit and credit came from a transfer between your two accounts|"
          r"debit dan kredit dengan jumlah yang sama berasal dari transfer antara dua rekening anda)"),
    _rule("refund_pending", "confirm", "credit_pending", "pending",
          r"(?:refund has been initiated but has not reached your account|pengembalian dana sudah diproses, tetapi belum masuk|"
          r"foreign-currency refund is still processing)"),
    _rule("non_cash_valuation", "irrelevant", "non_cash", "info",
          r"(?:displayed market value has|displayed value of the investment has|nilai investasi yang ditampilkan telah)"),
    _rule("prize_settled", "confirm", "credit_settled", "settled", r"prize proceeds have reached your account"),
    _rule("prize_pending", "new_income", "income_pending", "pending",
          r"(?:prize claim has been verified and is still in payment processing|"
          r"klaim hadiah anda sudah diverifikasi dan masih dalam proses pembayaran)"),
    _rule("failed_debit_retry", "confirm", "expense_existing", "confirmed", r"previous debit attempt failed"),
    _rule("duplicate_charge_investigated", "confirm", "expense_existing", "pending",
          r"(?:extra card charge is still being investigated|tagihan kartu tambahan masih dalam penyelidikan)"),
    _rule("investment_sale_settled", "confirm", "credit_settled", "settled",
          r"(?:proceeds from your investment sale have settled|hasil penjualan investasi anda sudah masuk)"),
    _rule("reimbursement_settled", "confirm", "credit_settled", "settled",
          r"(?:reimbursement for your earlier work expense|penggantian atas biaya kerja anda sebelumnya)"),
    _rule("receipt_final_amount", "confirm", "expense_existing", "settled", r"receipt (?:has|contains) the final (?:\w+ )?amount"),
    _rule("foreign_currency_charge", "confirm", "expense_existing", "pending",
          r"(?:bill was charged in a foreign currency|tagihan dikenakan dalam mata uang asing)"),
    _rule("separate_card_minimums", "confirm", "expense_existing", "confirmed", r"minimum payments due on two separate card accounts"),
    _rule("third_party_salary_claim", "new_income", "income_claim", "claimed",
          r"employer has confirmed a\s+" + MONEY + r"\s+salary credit for\s+" + LONG),
    _rule("cash_prize_offer", "irrelevant", "other", "info", r"(?:selected for a cash prize|terpilih untuk menerima hadiah uang tunai)"),
]

INSTRUCTION_PATTERNS = [
    ("payment_demand", re.compile(r"\b(?:pay|bayar)\b[^.]*?\b(?:today|now|immediately|hari ini|sekarang)\b", re.I)),
    ("estimate_directive", re.compile(r"(?:should be removed from future estimates|harus dikeluarkan dari perkiraan|"
                                      r"should be included in the upcoming payout|dapat dimasukkan dalam pembayaran berikutnya|"
                                      r"please use the revised date|gunakan tanggal terbaru)", re.I)),
    ("third_party_income_assertion", re.compile(r"employer has confirmed a\s+(?:IDR|INR|ZAR|USD|EUR)", re.I)),
]


@dataclass
class Claim:
    message_id: str
    user_id: str
    sent: date
    source_type: str
    related_event_id: str
    rule: str
    intent: str
    subject: str
    status: str
    span: str
    amount: float | None = None
    currency: str | None = None
    date: date | None = None
    pct: float | None = None
    supported: bool | None = None
    reason: str = ""
    effect: tuple | None = None


_PARSED: dict = {}
_EFFECTS: dict = {}


def parse_message(msg) -> list[Claim]:
    if msg.message_id in _PARSED:
        return [dataclasses.replace(c) for c in _PARSED[msg.message_id]]
    text = msg.message_text
    sent = date.fromisoformat(msg.sent_at[:10])
    claims = []
    for rule in RULES:
        m = rule.pattern.search(text)
        if not m:
            continue
        groups = m.groupdict()
        claim = Claim(msg.message_id, msg.user_id, sent, msg.source_type, msg.related_event_id, rule.name, rule.intent,
                      rule.subject, rule.status, m.group(0))
        if groups.get("num"):
            claim.amount = float(groups["num"].replace(",", ""))
            claim.currency = groups["cur"].upper()
        if groups.get("pct"):
            claim.pct = float(groups["pct"])
        iso = groups.get("date")
        if not iso and rule.date_pattern:
            dm = rule.date_pattern.search(text)
            if dm:
                iso = dm.group("date")
                claim.span += " ... " + dm.group(0)
        if iso:
            claim.date = date.fromisoformat(iso)
        if groups.get("long"):
            claim.date = datetime.strptime(groups["long"], "%d %B %Y").date()
        claims.append(claim)
    _PARSED[msg.message_id] = claims
    return [dataclasses.replace(c) for c in claims]


def instruction_sentences(msg) -> list[dict]:
    found = []
    for sentence in re.split(r"(?<=[.!?])\s+", msg.message_text):
        for category, pattern in INSTRUCTION_PATTERNS:
            if pattern.search(sentence):
                found.append({"message_id": msg.message_id, "user_id": msg.user_id, "source_type": msg.source_type,
                              "category": category, "text": sentence.strip(), "action": "ignored (not executed)"})
                break
    return found


# ---------------------------------------------------------------- support checks
def _transfer_pairs(events, before: date) -> set[str]:
    settled = [e for e in events if e.status == "settled" and not e.linked_event_id and e.amount_home is not None
               and e.cash_date <= before]
    credits = [e for e in settled if e.direction == "credit"]
    debits = [e for e in settled if e.direction == "debit"]
    ids: set[str] = set()
    for c in credits:
        for d in debits:
            if d.event_id not in ids and abs(d.amount_home - c.amount_home) <= 0.01 and abs((d.cash_date - c.cash_date).days) <= 3:
                ids |= {c.event_id, d.event_id}
                break
    return ids


def assess(claim: Claim, data, E) -> Claim:
    events = data.events_by_user.get(claim.user_id, [])
    cats = set(E.CONFIG["income_projection_categories"])
    salary_rows = [e for e in events if e.direction == "credit" and e.category in cats and e.status == "settled"
                   and e.cash_date <= claim.sent]

    def scheduled_credit_near(d: date | None) -> bool:
        return d is not None and any(e.direction == "credit" and e.status in ("scheduled", "pending")
                                     and abs((e.cash_date - d).days) <= 3 for e in events)

    subject = claim.subject
    if subject in ("income", "income_base", "income_remaining", "income_partial_end", "income_end", "income_resume"):
        # only the payer can amend, confirm, stop or resume salary; any other source is untrusted for income facts
        claim.supported = bool(salary_rows) and claim.source_type == "employer"
        if claim.source_type != "employer":
            claim.reason = f"salary change asserted by a {claim.source_type} message, not the employer"
        else:
            claim.reason = f"{len(salary_rows)} salary rows" if salary_rows else "no salary rows for this user"
    elif subject in ("income_new", "income_one_off"):
        claim.supported = scheduled_credit_near(claim.date)
        claim.reason = "scheduled credit row near date" if claim.supported else "no scheduled/pending credit row backs it"
    elif subject == "income_claim":
        backed = scheduled_credit_near(claim.date)
        claim.supported = claim.source_type == "employer" and backed
        claim.reason = ("employer message with scheduled row" if claim.supported else
                        f"asserted inside a {claim.source_type} message; {'a' if backed else 'no'} scheduled credit row")
    elif subject == "rent":
        rent_rows = [e for e in events if e.direction == "debit" and e.status == "settled"
                     and (e.category == "rent" or "rent" in e.description.lower())]
        claim.supported = len(rent_rows) >= 2
        claim.reason = f"{len(rent_rows)} rent rows" if rent_rows else "no rent rows"
    elif subject == "transfer":
        pairs = _transfer_pairs(events, claim.sent)
        claim.supported = bool(pairs)
        claim.reason = f"matched debit/credit pairs {sorted(pairs)}" if pairs else "no matching debit/credit pair"
    elif subject == "expense_new":
        claim.supported = False
        claim.reason = "no event row and no amount"
    elif claim.related_event_id:
        claim.supported = claim.related_event_id in data.events
        claim.reason = f"related_event_id {claim.related_event_id}"
    else:
        claim.supported = None
        claim.reason = "informational"
    claim.effect = _effect(claim, data, E)
    return claim


def _home(claim: Claim, data, E, on: date) -> float:
    home = data.profiles[claim.user_id].home_currency
    return E.to_home(data.fx, claim.amount, claim.currency, home, on)


def _effect(claim: Claim, data, E) -> tuple | None:
    cfg = E.CONFIG
    if claim.status in ("pending", "info", "settled") and claim.subject != "transfer":
        return None
    if claim.rule == "third_party_salary_claim":
        return None  # never: unsupported income asserted by a non-employer source
    if claim.subject == "expense_new":
        if cfg["unsupported_expense_policy"] == "include" and claim.amount and claim.date:
            return ("expense_add", _home(claim, data, E, claim.date), claim.date)
        return None
    if claim.subject in ("income_new", "income_one_off"):
        if claim.supported:
            return None  # already represented by its scheduled row
        if claim.subject == "income_new" and cfg["unsupported_income_policy"] == "include_confirmed" and claim.date:
            return ("income_add", _home(claim, data, E, claim.date), claim.date)
        if claim.subject == "income_one_off" and cfg["count_one_time_arrears"]:
            return ("income_topup_next", _home(claim, data, E, claim.sent), claim.sent)
        return None
    if not claim.supported:
        return None
    scope = "next" if cfg["temporary_income_change_scope"] == "next_only" else "all_future"
    rule = claim.rule
    if rule == "salary_increase":
        on = claim.date or claim.sent
        return ("income_amount", _home(claim, data, E, on), "from_date", on)
    if rule in ("temporary_pay", "reduced_next_salary", "regular_salary_next_payroll"):
        return ("income_amount", _home(claim, data, E, claim.sent), scope, claim.sent)
    if rule == "salary_confirmed_for_date" and claim.date:
        return ("income_amount", _home(claim, data, E, claim.date), "next", claim.sent)
    if rule == "base_salary_confirmed":
        return ("income_amount", _home(claim, data, E, claim.sent), "all_future", claim.sent)
    if rule == "remaining_salary":
        return ("income_keep_remaining", _home(claim, data, E, claim.sent))
    if rule == "salary_date_moved" and claim.date:
        return ("income_date", claim.date)
    if rule in ("seasonal_contract_ended", "employment_ended"):
        return ("income_stop",)
    if rule == "salary_resumes" and claim.date:
        return ("income_resume", _home(claim, data, E, claim.date), claim.date)
    if rule == "rent_increase" and claim.pct is not None:
        return ("rent_scale", 1 + claim.pct / 100, claim.sent)
    if rule == "internal_transfer":
        return ("exclude_ids", tuple(sorted(_transfer_pairs(data.events_by_user.get(claim.user_id, []), claim.sent))))
    return None


def claims_for(user_id: str, request_date: date, data, E) -> list[Claim]:
    cfg = E.CONFIG
    key = (user_id, request_date, id(data), cfg["message_visibility"], cfg["temporary_income_change_scope"],
           cfg["unsupported_income_policy"], cfg["unsupported_expense_policy"], cfg["count_one_time_arrears"],
           tuple(cfg["income_projection_categories"]))
    if key not in _EFFECTS:
        out = []
        for msg in sorted(data.messages_by_user.get(user_id, []), key=lambda m: (m.sent_at, m.message_id)):
            if cfg["message_visibility"] == "sent_on_or_before_request" and date.fromisoformat(msg.sent_at[:10]) > request_date:
                continue
            out.extend(assess(c, data, E) for c in parse_message(msg))
        _EFFECTS[key] = out
    return _EFFECTS[key]


def excluded_event_ids(user_id: str, request_date: date, data, E) -> set[str]:
    ids: set[str] = set()
    for c in claims_for(user_id, request_date, data, E):
        if c.effect and c.effect[0] == "exclude_ids":
            ids |= set(c.effect[1])
    return ids


def _add_month(d: date, dom: int) -> date:
    import calendar
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, min(dom, calendar.monthrange(y, m)[1]))


def apply_effects(items: list, user_id: str, request_date: date, start: date, end: date, data, E) -> list:
    claims = [c for c in claims_for(user_id, request_date, data, E) if c.effect and c.effect[0] != "exclude_ids"]
    if not claims:
        return items
    cats = set(E.CONFIG["income_projection_categories"])
    items = list(items)

    def is_salary(i) -> bool:
        return i.amount > 0 and i.category in cats and i.kind in ("projected", "scheduled", "message")

    def main_salary() -> list[int]:
        sal = [k for k, i in enumerate(items) if is_salary(i)]
        if not sal:
            return []
        top = max((items[k] for k in sal), key=lambda i: (i.amount, i.series_id)).series_id
        return sorted((k for k in sal if items[k].series_id == top or items[k].kind != "projected"), key=lambda k: items[k].date)

    # later messages override earlier ones; cancellations are applied last (explicit cancellation wins)
    for c in sorted(claims, key=lambda c: (c.effect[0] == "income_stop", c.sent, c.message_id)):
        kind = c.effect[0]
        tag = f" ({c.message_id})"
        if kind == "income_amount":
            _, amount, scope, on = c.effect
            targets = [k for k in main_salary() if items[k].date >= on]
            for k in (targets[:1] if scope == "next" else targets):
                items[k] = dataclasses.replace(items[k], amount=amount, description=items[k].description + tag)
        elif kind == "income_topup_next":
            _, amount, on = c.effect
            targets = [k for k in main_salary() if items[k].date >= on]
            if targets:
                k = targets[0]
                items[k] = dataclasses.replace(items[k], amount=items[k].amount + amount, description=items[k].description + tag)
        elif kind == "income_date":
            targets = [k for k in main_salary() if items[k].date >= request_date]
            if targets:
                k = targets[0]
                if c.effect[1] > end:
                    items.pop(k)
                else:
                    items[k] = dataclasses.replace(items[k], date=max(c.effect[1], start), description=items[k].description + tag)
        elif kind == "income_keep_remaining":
            amount = c.effect[1]
            groups = defaultdict(list)
            for k, i in enumerate(items):
                if is_salary(i) and i.kind == "projected":
                    groups[i.series_id].append(k)
            if groups:
                keep = min(groups, key=lambda sid: abs(items[groups[sid][0]].amount - amount))
                for k in groups[keep]:
                    items[k] = dataclasses.replace(items[k], amount=amount, description=items[k].description + tag)
                drop = {k for sid, ks in groups.items() if sid != keep for k in ks}
                items = [i for k, i in enumerate(items) if k not in drop]
        elif kind == "income_resume":
            _, amount, on = c.effect
            d = on
            while d <= end:
                if d >= start:
                    near = [k for k, i in enumerate(items) if is_salary(i) and abs((i.date - d).days) <= 7]
                    if near:
                        for k in near:
                            items[k] = dataclasses.replace(items[k], amount=amount, description=items[k].description + tag)
                    else:
                        items.append(E.LedgerItem(d, amount, "message", c.message_id, "message|salary_resume",
                                                  "resumed salary" + tag, "salary", "fixed"))
                d = _add_month(d, on.day)
        elif kind in ("income_add", "expense_add"):
            _, amount, d = c.effect
            if start <= d <= end:
                sign = 1 if kind == "income_add" else -1
                items.append(E.LedgerItem(d, sign * amount, "message", c.message_id, f"message|{c.rule}",
                                          c.rule + tag, "salary" if sign > 0 else "other", "fixed"))
        elif kind == "rent_scale":
            _, factor, on = c.effect
            for k, i in enumerate(items):
                if (i.kind == "projected" and i.amount < 0 and i.date >= on
                        and (i.category == "rent" or "rent" in i.description.lower())):
                    items[k] = dataclasses.replace(i, amount=round(i.amount * factor, 2), description=i.description + tag)
        elif kind == "income_stop":
            items = [i for i in items if not (is_salary(i) and i.kind in ("projected", "message"))]
    return items


# ---------------------------------------------------------------- CLI report
def main() -> None:
    sys.path.insert(0, str(CODE_DIR))
    import engine as E

    data = E.get_data()
    request_date_by_user = {r.user_id: r.request_date for r in data.requests.values()}
    messages = sorted((m for ms in data.messages_by_user.values() for m in ms), key=lambda m: int(m.message_id.split("_")[1]))
    matched, blocked, shown, irrelevant_rule_hits = 0, [], [], 0
    for msg in messages:
        claims = [assess(c, data, E) for c in parse_message(msg)]
        blocked.extend(instruction_sentences(msg))
        if claims:
            matched += 1
        for c in claims:
            if c.intent == "irrelevant":
                irrelevant_rule_hits += 1
                continue
            visible = c.sent <= request_date_by_user.get(c.user_id, c.sent)
            shown.append((c, visible))

    print(f"{'message':<12}{'user':<9}{'rule':<30}{'intent':<15}{'supp':<6}{'effect':<24}{'amount':>16} {'date':<11} matched span")
    for c, visible in shown:
        amount = f"{c.currency} {c.amount:,.2f}" if c.amount is not None else (f"{c.pct:g}%" if c.pct is not None else "")
        effect = c.effect[0] if c.effect else "-"
        supp = {True: "yes", False: "NO", None: "n/a"}[c.supported]
        print(f"{c.message_id:<12}{c.user_id:<9}{c.rule:<30}{c.intent:<15}{supp:<6}{effect + ('' if visible else ' (late)'):<24}"
              f"{amount:>16} {str(c.date or ''):<11} \"{c.span[:110]}\"")
    print(f"\ncoverage: {matched}/{len(messages)} messages matched at least one rule; "
          f"{len(messages) - matched} fell through to irrelevant; {len(shown)} non-irrelevant claims; "
          f"{irrelevant_rule_hits} matched an explicitly-irrelevant rule")
    unmatched = [m.message_id for m in messages if not parse_message(m)]
    print("unmatched:", unmatched or "none")

    BLOCKED_PATH.write_text(json.dumps({"source": "messages.csv (deterministic scan)", "count": len(blocked),
                                        "items": blocked}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nblocked instruction-like sentences: {len(blocked)} -> {BLOCKED_PATH}")
    for b in blocked:
        print(f"  {b['message_id']:<12}{b['category']:<30}{b['text']}")

    for msg in messages:  # every income claim asserted inside a non-payer message must be rejected
        for c in parse_message(msg):
            if c.rule == "third_party_salary_claim":
                c = assess(c, data, E)
                print(f"\n{c.message_id} third-party salary claim: supported={c.supported} effect={c.effect} "
                      f"reason={c.reason!r} -> {'REJECTED' if c.effect is None else 'ACCEPTED (bug)'}")


if __name__ == "__main__":
    main()
