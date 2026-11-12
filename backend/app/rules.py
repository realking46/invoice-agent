"""Decision rules. Deterministic, one function per check, each returning a RuleResult with a plain-English
reason and the numbers it compared. The LLM never decides; these do.

Severity: Reject > Hold for review > Approve with note > Approve. The most severe outcome wins."""
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Optional

from rapidfuzz import fuzz
from sqlmodel import Session, select

from . import config
from .db import InvoiceRecord, POLine, PurchaseOrder, Vendor, engine
from .extract import gstin_valid

APPROVE, NOTE, HOLD, REJECT = "Approve", "Approve with note", "Hold for review", "Reject"
SEVERITY = {APPROVE: 0, NOTE: 1, HOLD: 2, REJECT: 3}
STATUS_FOR = {None: "pass", NOTE: "note", HOLD: "warn", REJECT: "fail"}
ACCEPTED = (APPROVE, NOTE)                 # decisions that consume PO quantity
ENTERED = (APPROVE, NOTE, HOLD)            # decisions that make an invoice "already in the system"
PAST = {APPROVE: "approved", NOTE: "approved with a note", HOLD: "on hold", REJECT: "rejected"}
# When several rules agree on the outcome, lead the summary with the one a buyer cares about most.
SUMMARY_PRIORITY = ["R6", "R7", "R0", "R4b", "R11", "R10", "R9", "R12", "R5", "R1", "R8", "R3", "R4", "R2"]


@dataclass
class RuleResult:
    id: str
    name: str
    outcome: Optional[str]            # None = passed
    reason: str
    evidence: dict = field(default_factory=dict)
    skipped: bool = False

    @property
    def status(self):
        return "skip" if self.skipped else STATUS_FOR[self.outcome]


def inr(x) -> str:
    if x is None:
        return "—"
    neg = x < 0
    whole, frac = f"{abs(x):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join(([head] if head else []) + parts + [tail])
    s = f"₹{whole}" + ("" if frac == "00" else f".{frac}")
    return ("-" if neg else "") + s


def normalise_invoice_no(s: Optional[str]) -> Optional[str]:
    """'INV-0042', 'inv 42', 'INV/042' -> 'INV42'. Keeps the digits that matter, drops formatting."""
    if not s:
        return None
    parts = re.findall(r"[A-Z]+|\d+", s.upper())          # split on any separator and letter/digit boundary
    return "".join(p.lstrip("0") or "0" if p.isdigit() else p for p in parts) or None


def tolerance(base_amount: float) -> float:
    """A5: ±price_tolerance_pct % of the base, capped at price_tolerance_abs rupees (whichever is lower)."""
    st = config.SETTINGS
    return min(abs(base_amount) * st["price_tolerance_pct"] / 100, st["price_tolerance_abs"])


def stage_status(results: list[RuleResult]) -> str:
    order = ["skip", "pass", "note", "warn", "fail"]
    return max((r.status for r in results), key=order.index, default="pass")


def worst(results: list[RuleResult]) -> Optional[str]:
    outs = [r.outcome for r in results if r.outcome]
    return max(outs, key=SEVERITY.get) if outs else None


def pack(results: list[RuleResult], extra: dict | None = None) -> dict:
    return {"rules": [{**asdict(r), "status": r.status} for r in results], **(extra or {})}


def reading_coverage(ext_res) -> tuple[int, int]:
    """How many of the key fields the reader found at all."""
    from .schemas import KEY_FIELDS
    fields = [f for f in KEY_FIELDS if f not in ("po_reference", "bank_account", "ifsc")]
    found = sum(1 for f in fields if getattr(ext_res.data, f) not in (None, ""))
    return found, len(fields)


def poor_reading(ext_res) -> bool:
    """The reader found under half of the key fields: the layout is unfamiliar (or the AI reader was unavailable).
    Then an absent field says nothing about the invoice, only about the reader."""
    found, total = reading_coverage(ext_res)
    return found * 2 < total


# ================================================================ VALIDATE: R0–R4
def validate(ext_res) -> list[RuleResult]:
    d = ext_res.data
    out = []
    found, total = reading_coverage(ext_res)
    poor = found * 2 < total
    if poor:
        who = "the local reader (AI reader unavailable)" if ext_res.fallback_reason else (
            "the AI reader" if ext_res.mode == "llm" else "the local reader")
        out.append(RuleResult("R0", "Reading coverage", HOLD,
                              f"Only {found} of {total} key fields could be read by {who}; this layout isn't one it "
                              f"knows. A person should check the original rather than trust what is missing.",
                              {"found": found, "of": total}))
    else:
        out.append(RuleResult("R0", "Reading coverage", None, f"{found} of {total} key fields read."))
    required = ["invoice_number", "invoice_date", "total"]
    missing = [f for f in required if f in ext_res.missing_fields]
    if not (d.vendor_name or d.vendor_gstin):
        missing.append("vendor")
    unreadable = [f for f in required if f in ext_res.unreadable_fields]
    if poor:  # not found by a reader that found almost nothing: unreadable, not missing
        unreadable, missing = sorted(set(unreadable) | set(missing), key=(required + ["vendor"]).index), []
    def pretty(fs):
        names = [f.replace("_", " ") for f in fs]
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]
    if missing:
        out.append(RuleResult("R1", "Required fields present", REJECT,
                              f"Invoice has no {pretty(missing)}; it cannot be booked. A request to the vendor is drafted.",
                              {"missing": missing}))
    elif unreadable:
        out.append(RuleResult("R1", "Required fields present", HOLD,
                              f"Could not read {pretty(unreadable)}" + ("" if poor else " on the scan") +
                              "; a person should check the original.",
                              {"unreadable": unreadable}))
    else:
        out.append(RuleResult("R1", "Required fields present", None, "Invoice number, date, vendor and total found."))

    floor = config.SETTINGS["confidence_floor"]
    low = [f for f in ext_res.low_confidence_fields if f != "po_reference"]
    if low:
        worst_f = min(low, key=lambda f: d.confidence.get(f, 0))
        out.append(RuleResult("R2", "Extraction confidence", HOLD,
                              f"{len(low)} field(s) read with low confidence (lowest: {worst_f.replace('_', ' ')} at "
                              f"{d.confidence.get(worst_f, 0):.2f}); needs a human check.",
                              {"low_confidence": {f: d.confidence.get(f) for f in low}, "floor": floor}))
    else:
        out.append(RuleResult("R2", "Extraction confidence", None, f"All key fields read at ≥ {floor:.2f} confidence."))

    arith = [c for c in ext_res.checks if "check" in c and c["check"] != "vendor GSTIN checksum"]
    failed = [c for c in arith if not c["passed"]]
    if failed:
        out.append(RuleResult("R3", "Arithmetic", HOLD,
                              "Numbers on the invoice don't add up: " + "; ".join(
                                  f"{c['check']} ({c['detail']})" for c in failed), {"checks": arith}))
    elif arith:
        out.append(RuleResult("R3", "Arithmetic", None, "Line items, subtotal, tax and total are consistent.",
                              {"checks": arith}))
    else:
        out.append(RuleResult("R3", "Arithmetic", None, "Not enough figures to cross-check.", skipped=True))

    out.append(tax_sanity(d))
    cur = (d.currency or "INR").upper()
    if cur != "INR":
        out.append(RuleResult("R4b", "Currency", HOLD,
                              f"Invoice is in {cur}; this process handles INR invoices only. A person should check the "
                              f"vendor and the conversion before paying.", {"currency": cur}))
    return out


def tax_sanity(d) -> RuleResult:
    if not d.tax_lines:
        return RuleResult("R4", "Tax sanity", None, "No tax lines found.", skipped=True)
    types = {t.type for t in d.tax_lines}
    total_rate = sum(t.rate or 0 for t in d.tax_lines)
    ev = {"tax_lines": [t.model_dump() for t in d.tax_lines], "total_rate": total_rate}
    if round(total_rate, 2) not in (5, 12, 18, 28):
        return RuleResult("R4", "Tax sanity", HOLD, f"Total GST rate {total_rate:g}% is not a standard slab.", ev)
    if {"CGST", "SGST"} <= types:
        c = next(t for t in d.tax_lines if t.type == "CGST")
        s = next(t for t in d.tax_lines if t.type == "SGST")
        if abs(c.amount - s.amount) > 1:
            return RuleResult("R4", "Tax sanity", HOLD, f"CGST {inr(c.amount)} and SGST {inr(s.amount)} differ.", ev)
    vstate = (d.vendor_gstin or "")[:2]
    intra = vstate == config.BUYER_GSTIN[:2]
    if vstate.isdigit() and gstin_valid(d.vendor_gstin):
        if intra and "IGST" in types:
            return RuleResult("R4", "Tax sanity", NOTE, "Same-state vendor charged IGST; expected CGST + SGST.", ev)
        if not intra and {"CGST", "SGST"} & types:
            return RuleResult("R4", "Tax sanity", NOTE, "Out-of-state vendor charged CGST/SGST; expected IGST.", ev)
    return RuleResult("R4", "Tax sanity", None,
                      f"GST {total_rate:g}% ({' + '.join(sorted(types))}) is valid for this vendor.", ev)


# ================================================================ VENDOR: R5–R6
def match_vendor(d) -> tuple[Optional[Vendor], float, str]:
    with Session(engine) as s:
        vendors = s.exec(select(Vendor)).all()
    if d.vendor_gstin:
        for v in vendors:
            if v.gstin == d.vendor_gstin:
                return v, 0.99, "GSTIN exact match"
    best, score = None, 0
    if d.vendor_name:
        for v in vendors:
            names = [v.legal_name] + [a for a in v.aliases.split("|") if a]
            sc = max(fuzz.token_set_ratio(d.vendor_name.lower(), n.lower()) for n in names)
            if sc > score:
                best, score = v, sc
    if best and score >= 85:
        return best, round(score / 100, 2), f"name match ({score:.0f}%)"
    return None, 0.0, "no match"


def vendor_checks(d, ctx) -> list[RuleResult]:
    v, conf, how = match_vendor(d)
    ctx["vendor"], ctx["vendor_conf"] = v, conf
    out = []
    if not v:
        who = d.vendor_name or d.vendor_gstin or "unknown"
        unsure = d.confidence.get("vendor_name", 0) < config.SETTINGS["confidence_floor"] or ctx.get("poor_read")
        out.append(RuleResult("R5", "Approved vendor", HOLD if unsure else REJECT,
                              f"Vendor '{who}' is not in the vendor master" +
                              (" (the invoice was only partly read; check manually)." if ctx.get("poor_read") else
                               " (name read with low confidence; check manually)." if unsure else
                               "; onboard them before paying."), {"read_name": d.vendor_name, "read_gstin": d.vendor_gstin}))
        out.append(RuleResult("R6", "Bank details", None, "Skipped: no vendor on file.", skipped=True))
        return out
    ev = {"vendor_id": v.vendor_id, "legal_name": v.legal_name, "matched_by": how, "match_confidence": conf}
    if v.status != "approved":
        out.append(RuleResult("R5", "Approved vendor", REJECT, f"{v.legal_name} is {v.status} in the vendor master.", ev))
    elif d.vendor_gstin and d.vendor_gstin != v.gstin:
        if gstin_valid(d.vendor_gstin):
            out.append(RuleResult("R5", "Approved vendor", HOLD,
                                  f"Name matches {v.legal_name} but GSTIN {d.vendor_gstin} differs from the one on "
                                  f"file ({v.gstin}); possible impersonation.", ev))
        else:
            out.append(RuleResult("R5", "Approved vendor", None,
                                  f"Matched {v.legal_name} by {how}; GSTIN on the invoice looks misread "
                                  f"({d.vendor_gstin}, invalid checksum).", ev))
    else:
        out.append(RuleResult("R5", "Approved vendor", None, f"{v.legal_name} is an approved vendor ({how}).", ev))

    acct, ifsc = d.bank_account, d.ifsc
    bev = {"invoice_account": acct, "invoice_ifsc": ifsc, "master_account": "…" + v.bank_account[-4:],
           "master_ifsc": v.ifsc}
    if not acct and not ifsc:
        out.append(RuleResult("R6", "Bank details", None, "No bank details on the invoice; pay to the account on file.",
                              bev))
    elif acct == v.bank_account and (ifsc in (None, v.ifsc)):
        out.append(RuleResult("R6", "Bank details", None, "Bank account matches the vendor master.", bev))
    else:
        out.append(RuleResult(
            "R6", "Bank details", HOLD,
            f"Bank account on the invoice (…{(acct or '????')[-4:]}, {ifsc}) differs from the one on file "
            f"(…{v.bank_account[-4:]}, {v.ifsc}). Possible payment fraud: confirm by calling the vendor on the "
            f"number on file, not one on the invoice." + (" The invoice itself announces a change." if d.notes else ""),
            bev))
    return out


# ================================================================ DUPLICATE: R7–R8
def prior_invoices(run_id: int, vendor_id: str) -> list[InvoiceRecord]:
    with Session(engine) as s:
        return s.exec(select(InvoiceRecord).where(InvoiceRecord.vendor_id == vendor_id,
                                                  InvoiceRecord.run_id != run_id,
                                                  InvoiceRecord.decision.in_(ENTERED))).all()


def duplicate_checks(d, ctx) -> list[RuleResult]:
    out = []
    if ctx.get("same_file_run"):
        out.append(RuleResult("R7", "Duplicate (exact)", REJECT,
                              f"This exact file was already processed in run #{ctx['same_file_run']}.",
                              {"duplicate_of_run": ctx["same_file_run"]}))
        return out
    v = ctx.get("vendor")
    if not v:
        return [RuleResult("R7", "Duplicate (exact)", None, "Skipped: vendor unknown.", skipped=True)]
    prior = prior_invoices(ctx["run"].id, v.vendor_id)
    norm = normalise_invoice_no(d.invoice_number)
    exact = next((p for p in prior if norm and p.invoice_no_normalised == norm), None)
    if exact:
        same_text = exact.invoice_no == d.invoice_number
        out.append(RuleResult("R7", "Duplicate (exact)", REJECT,
                              f"Duplicate of {exact.invoice_no} from {v.legal_name}, already {PAST[exact.decision]} "
                              f"in run #{exact.run_id}" + ("" if same_text else
                                                            f" (number written as '{d.invoice_number}')") + ".",
                              {"duplicate_of_run": exact.run_id, "normalised": norm, "prior_number": exact.invoice_no}))
        return out
    out.append(RuleResult("R7", "Duplicate (exact)", None,
                          f"No earlier invoice {norm or '—'} from this vendor ({len(prior)} on file).", {"normalised": norm}))
    st = config.SETTINGS
    amount = d.total if d.total is not None else ((d.subtotal or 0) + (d.tax_total or 0))
    probable = []
    for p in prior:
        if p.total is None or not amount:
            continue
        pct = abs(p.total - amount) / max(p.total, 1) * 100
        days = None
        if p.invoice_date and d.invoice_date:
            days = abs((date.fromisoformat(p.invoice_date) - date.fromisoformat(d.invoice_date)).days)
        if pct <= st["duplicate_amount_pct"] and (days is None or days <= st["duplicate_window_days"]):
            probable.append((p, pct, days))
    if probable:
        p, pct, days = probable[0]
        out.append(RuleResult("R8", "Duplicate (probable)", HOLD,
                              f"Looks like a re-send of {p.invoice_no} (run #{p.run_id}): amount within {pct:.1f}%"
                              + (f", {days} days apart." if days is not None else "."),
                              {"candidate_run": p.run_id, "amount_diff_pct": round(pct, 2), "days_apart": days}))
    else:
        out.append(RuleResult("R8", "Duplicate (probable)", None, "No similar invoice (amount and date) from this vendor."))
    return out


# ================================================================ PO MATCH: R9–R12
def _po_bundle(po_number):
    with Session(engine) as s:
        po = s.get(PurchaseOrder, po_number)
        lines = s.exec(select(POLine).where(POLine.po_number == po_number).order_by(POLine.line_no)).all() if po else []
    return po, lines


def consumed(po_number: str, run_id: int) -> dict[int, float]:
    """Quantity per PO line already billed by accepted invoices (A6)."""
    with Session(engine) as s:
        recs = s.exec(select(InvoiceRecord).where(InvoiceRecord.po_number == po_number,
                                                  InvoiceRecord.run_id != run_id,
                                                  InvoiceRecord.decision.in_(ACCEPTED))).all()
    total: dict[int, float] = {}
    for r in recs:
        for k, q in json.loads(r.consumption_json or "{}").items():
            total[int(k)] = total.get(int(k), 0) + q
    return total


def infer_po(d, vendor) -> list[dict]:
    """No PO on the invoice: score this vendor's open POs on amount closeness + item similarity."""
    with Session(engine) as s:
        pos = s.exec(select(PurchaseOrder).where(PurchaseOrder.vendor_id == vendor.vendor_id,
                                                 PurchaseOrder.status == "open")).all()
    inv_text = " ".join(li.description for li in d.line_items).lower()
    amount = d.subtotal or (sum(li.amount or 0 for li in d.line_items))
    cands = []
    for po in pos:
        _, lines = _po_bundle(po.po_number)
        po_text = " ".join(l.description for l in lines).lower()
        item_sim = fuzz.token_set_ratio(inv_text, po_text) / 100 if inv_text else 0
        # keyword overlap catches bundled descriptions ("gloves, goggles, ear plugs" vs three PO lines)
        words = {w for w in re.findall(r"[a-z]{4,}", po_text)}
        overlap = len(words & set(re.findall(r"[a-z]{4,}", inv_text))) / max(len(words), 1)
        amt_sim = max(0.0, 1 - abs(po.subtotal - amount) / max(po.subtotal, 1) * 5) if amount else 0
        score = round(0.5 * amt_sim + 0.25 * item_sim + 0.25 * min(1, overlap * 2), 2)
        cands.append({"po_number": po.po_number, "score": score, "amount_similarity": round(amt_sim, 2),
                      "item_similarity": round(item_sim, 2), "keyword_overlap": round(overlap, 2),
                      "po_subtotal": po.subtotal})
    return sorted(cands, key=lambda c: -c["score"])


def po_checks(d, ctx) -> list[RuleResult]:
    out = []
    v = ctx.get("vendor")
    ctx["consumption"] = {}
    if not v:
        return [RuleResult("R9", "PO found", None, "Skipped: vendor unknown.", skipped=True)]

    inferred = False
    po_no = (d.po_reference or "").upper().replace(" ", "-") or None
    if po_no:
        po, lines = _po_bundle(po_no)
        if not po:
            return [RuleResult("R9", "PO found", HOLD, f"{po_no} is cited but does not exist in the PO register.",
                               {"cited": po_no})]
        if po.vendor_id != v.vendor_id:
            return [RuleResult("R9", "PO found", HOLD, f"{po_no} belongs to a different vendor ({po.vendor_id}).",
                               {"cited": po_no})]
        if po.status != "open":
            return [RuleResult("R9", "PO found", HOLD, f"{po_no} is {po.status}; no further billing expected.",
                               {"cited": po_no})]
        out.append(RuleResult("R9", "PO found", None, f"Invoice cites {po_no}, an open PO for {v.legal_name}.",
                              {"po_number": po_no}))
        ctx["po_conf"] = 0.99
    else:
        cands = infer_po(d, v)
        if not cands or cands[0]["score"] < 0.5:
            return [RuleResult("R9", "PO found", HOLD, "No PO cited and no open PO for this vendor fits the invoice.",
                               {"candidates": cands[:3]})]
        best = cands[0]
        po_no, inferred = best["po_number"], True
        po, lines = _po_bundle(po_no)
        runner = f"; next best {cands[1]['po_number']} at {cands[1]['score']:.2f}" if len(cands) > 1 else ""
        ctx["po_conf"] = min(best["score"], 0.79)
        out.append(RuleResult("R9", "PO found", HOLD,
                              f"No PO cited. Best match is {po_no} (score {best['score']:.2f}{runner}). "
                              f"Confirm the PO before approving.", {"inferred_po": po_no, "candidates": cands[:3]}))
    ctx["po"] = po

    # ---- line-level matching (R10, R11)
    already = consumed(po.po_number, ctx["run"].id)
    used, matches, extras = set(), [], []
    for li in d.line_items:
        best, sc = None, 0
        for pl in lines:
            if pl.line_no in used:
                continue
            s = fuzz.token_set_ratio(li.description.lower(), pl.description.lower())
            if s > sc:
                best, sc = pl, s
        if best and sc >= 70 and li.quantity is not None:
            used.add(best.line_no)
            matches.append((li, best, sc))
        else:
            extras.append(li)
    bundled = inferred or (len(d.line_items) == 1 and len(lines) > 1 and not matches)

    if bundled:
        out.append(RuleResult("R10", "Line prices", None,
                              "Invoice bills the order as one bundled lot; compared at total level instead.",
                              {"bundled": True}, skipped=True))
        out.append(RuleResult("R11", "Cumulative quantity", None, "Quantities not itemised; cannot check per line.",
                              skipped=True))
    else:
        price_issues, qty_issues, rows = [], [], []
        for li, pl, sc in matches:
            diff = (li.unit_price - pl.unit_price) * li.quantity
            allowed = tolerance(pl.unit_price * li.quantity)
            prev = already.get(pl.line_no, 0)
            rows.append({"invoice_line": li.description, "po_line": pl.line_no, "po_desc": pl.description,
                         "qty": li.quantity, "po_qty": pl.qty, "already_billed": prev,
                         "unit_price": li.unit_price, "po_unit_price": pl.unit_price, "match_score": sc})
            if diff > allowed + 0.01:
                pct = (li.unit_price - pl.unit_price) / pl.unit_price * 100
                price_issues.append(f"'{pl.description}' billed at {inr(li.unit_price)}/unit vs PO "
                                    f"{inr(pl.unit_price)} ({pct:+.1f}%, {inr(diff)} over, limit {inr(allowed)})")
            if prev + li.quantity > pl.qty + 1e-9:
                over = prev + li.quantity - pl.qty
                can = max(pl.qty - prev, 0)
                qty_issues.append(f"{po.po_number} line {pl.line_no} ordered {pl.qty:g} {pl.uom}; {prev:g} already "
                                  f"billed; this invoice bills {li.quantity:g} ({over:g} over). "
                                  f"Approve {can:g}, query {over:g} with the vendor.")
            ctx["consumption"][pl.line_no] = li.quantity
        out.append(RuleResult("R10", "Line prices", HOLD if price_issues else None,
                              "; ".join(price_issues) if price_issues else
                              f"All {len(matches)} matched line(s) priced within tolerance.", {"lines": rows}))
        out.append(RuleResult("R11", "Cumulative quantity", HOLD if qty_issues else None,
                              "; ".join(qty_issues) if qty_issues else
                              "Quantities fit within what is left on the PO" +
                              (f" ({sum(already.values()):g} units billed earlier)." if already else "."),
                              {"lines": rows, "previously_billed": already}))

    # ---- total variance (R12)
    if bundled:
        exp_sub = sum(pl.qty * pl.unit_price for pl in lines) - sum(
            already.get(pl.line_no, 0) * pl.unit_price for pl in lines)
        exp_tax = sum((pl.qty - already.get(pl.line_no, 0)) * pl.unit_price * pl.tax_rate / 100 for pl in lines)
    else:
        exp_sub = sum(li.quantity * pl.unit_price for li, pl, _ in matches)
        exp_tax = sum(li.quantity * pl.unit_price * pl.tax_rate / 100 for li, pl, _ in matches)
    exp_total = exp_sub + exp_tax
    inv_total = d.total if d.total is not None else ((d.subtotal or 0) + (d.tax_total or 0))
    diff = inv_total - exp_total
    allowed = tolerance(exp_total)
    ev = {"expected_total": round(exp_total, 2), "invoice_total": inv_total, "difference": round(diff, 2),
          "allowed": round(allowed, 2), "extra_lines": [e.description for e in extras]}
    extra_txt = f" from extra line(s): {', '.join(e.description for e in extras)}" if extras else ""
    if abs(diff) <= 1:
        out.append(RuleResult("R12", "Total vs PO", None, f"Total {inr(inv_total)} matches the PO prices for the quantities billed.", ev))
    elif abs(diff) <= allowed:
        out.append(RuleResult("R12", "Total vs PO", NOTE,
                              f"Total is {inr(abs(diff))} {'above' if diff > 0 else 'below'} the PO value "
                              f"({diff / exp_total * 100:+.2f}%){extra_txt}; within the {inr(allowed)} tolerance.", ev))
    else:
        out.append(RuleResult("R12", "Total vs PO", HOLD,
                              f"Total is {inr(abs(diff))} {'above' if diff > 0 else 'below'} the expected "
                              f"{inr(exp_total)}{extra_txt}; tolerance is {inr(allowed)}.", ev))
    return out


# ================================================================ DECIDE + OUTPUT
def decide(all_results: list[RuleResult], ctx) -> dict:
    decision = worst(all_results) or APPROVE
    drivers = [r for r in all_results if r.outcome == decision] if decision != APPROVE else []
    drivers.sort(key=lambda r: SUMMARY_PRIORITY.index(r.id) if r.id in SUMMARY_PRIORITY else 99)
    ext = ctx["extraction"].data
    key_conf = [ext.confidence.get(f, 0) for f in ("vendor_name", "invoice_number", "total", "subtotal")
                if getattr(ext, f) is not None]
    conf = round(min(key_conf + [ctx.get("vendor_conf", 0) or 0.5, ctx.get("po_conf", 0.99)]), 2)
    if decision == APPROVE:
        summary = "All checks passed: approved vendor, matching PO, prices and quantities within limits."
    else:
        summary = drivers[0].reason
        if len(drivers) > 1:
            summary += f" (+{len(drivers) - 1} more issue{'s' if len(drivers) > 2 else ''})"
    return {"decision": decision, "confidence": conf, "summary": summary,
            "drivers": [{"id": r.id, "name": r.name, "reason": r.reason} for r in drivers],
            "counts": {s: sum(1 for r in all_results if r.status == s) for s in ("pass", "note", "warn", "fail", "skip")}}


def next_action(decision: dict, all_results: list[RuleResult], ctx) -> dict:
    d, v = ctx["extraction"].data, ctx.get("vendor")
    ids = {r.id for r in all_results if r.outcome == decision["decision"]}
    act = {"decision": decision["decision"]}
    if decision["decision"] in (APPROVE, NOTE):
        due = None
        if d.invoice_date and v:
            due = (date.fromisoformat(d.invoice_date) + timedelta(days=v.payment_terms_days)).isoformat()
        act["action"] = f"Ready for payment to the account on file" + (f", due {due}." if due else ".")
        act["due_date"] = due
    elif decision["decision"] == HOLD:
        if "R6" in ids:
            act["action"] = "Treasury: verify the bank change by phone with the vendor's known contact before payment."
            act["owner"] = "Treasury / AP lead"
        elif "R9" in ids:
            act["action"] = "AP: confirm the suggested PO against the original order, then approve or reassign."
            act["owner"] = "AP clerk"
        elif "R11" in ids or "R10" in ids or "R12" in ids:
            act["action"] = "Procurement: confirm the over-billed quantity or price with the vendor."
            act["owner"] = "Procurement buyer"
        else:
            act["action"] = "AP: review the flagged fields against the original document."
            act["owner"] = "AP clerk"
    else:
        act["owner"] = "AP clerk"
        if "R1" in ids:
            act["action"] = "Send the vendor the drafted request for a corrected invoice."
            missing = next(r for r in all_results if r.id == "R1").evidence.get("missing", [])
            act["vendor_email"] = vendor_email(v, d, missing)
        elif "R7" in ids:
            act["action"] = "No payment. Tell the vendor this invoice was already received."
            act["vendor_email"] = vendor_email(v, d, [], duplicate_of=next(
                r for r in all_results if r.id == "R7").evidence.get("prior_number"))
        else:
            act["action"] = "No payment. Vendor must be onboarded or unblocked first."
    return act


def vendor_email(v, d, missing, duplicate_of=None) -> dict:
    name = v.legal_name if v else (d.vendor_name or "Vendor")
    ref = d.invoice_number or f"your invoice dated {d.invoice_date or '(undated)'}" + (
        f" against {d.po_reference}" if d.po_reference else "")
    if duplicate_of:
        body = (f"Dear {name} team,\n\nWe received invoice {d.invoice_number}, which matches invoice {duplicate_of} "
                f"already in our system. We will not process it again. If this is a new charge, please send a new "
                f"invoice with a unique number and a short note on what it covers.\n\nRegards,\nAccounts Payable\n"
                f"{config.BUYER_NAME}")
        return {"to": name, "subject": f"Duplicate invoice {d.invoice_number}", "body": body}
    items = "\n".join(f"  - {f.replace('_', ' ').capitalize()}" for f in missing)
    body = (f"Dear {name} team,\n\nThank you for {ref}. We cannot process it yet because the following "
            f"required details are missing:\n{items}\n\nPlease send a corrected invoice with these filled in. "
            f"Once received, we will process it within 2 working days.\n\nRegards,\nAccounts Payable\n{config.BUYER_NAME}")
    return {"to": name, "subject": f"Action needed: corrected invoice for {d.po_reference or 'your recent invoice'}",
            "body": body}
