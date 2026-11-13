"""Features around the core process: exports, master data editing, partial approval, reviewer insights."""
import csv
import io
import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from . import config
from .db import POLine, PurchaseOrder, Run, RunStep, InvoiceRecord, Vendor, audit, engine
from .extract import gstin_valid

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- 2. exports
CSV_COLUMNS = ["id", "file_name", "started_at", "vendor", "invoice_no", "po_number", "po_inferred", "currency",
               "total", "approved_amount", "due_date", "system_decision", "decision", "reviewed_by", "review_note",
               "reason_summary", "confidence", "processing_ms"]


@router.get("/runs.csv")
def runs_csv():
    from .main import _run_rows
    with Session(engine) as s:
        rows = _run_rows(s)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="invoice-decisions-{stamp}.csv"'})


@router.get("/runs/{run_id}/decision.json")
def decision_json(run_id: int):
    from .main import get_run
    body = get_run(run_id)
    return Response(json.dumps(body, default=str, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="decision-run-{run_id}.json"'})


# ---------------------------------------------------------------- 5. vendor and PO master
@router.get("/master/full")
def master_full():
    with Session(engine) as s:
        vendors = s.exec(select(Vendor).order_by(Vendor.vendor_id)).all()
        pos = s.exec(select(PurchaseOrder).order_by(PurchaseOrder.po_number)).all()
        lines = s.exec(select(POLine).order_by(POLine.po_number, POLine.line_no)).all()
    by_po: dict = {}
    for l in lines:
        by_po.setdefault(l.po_number, []).append(l.model_dump())
    names = {v.vendor_id: v.legal_name for v in vendors}
    return {"vendors": [v.model_dump() for v in vendors],
            "purchase_orders": [{**p.model_dump(), "vendor_name": names.get(p.vendor_id), "lines": by_po.get(p.po_number, [])}
                                for p in pos]}


class NewVendor(BaseModel):
    legal_name: str
    gstin: str
    address: str = ""
    bank_account: str
    ifsc: str
    payment_terms_days: int = 30
    aliases: str = ""


@router.post("/vendors")
def add_vendor(v: NewVendor):
    name = v.legal_name.strip()
    gstin = v.gstin.strip().upper()
    if not name:
        raise HTTPException(400, "Enter the vendor's legal name.")
    if not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", gstin):
        raise HTTPException(400, "GSTIN must be 15 characters, like 27AAKFS1234L1ZZ.")
    if not gstin_valid(gstin):
        raise HTTPException(400, "That GSTIN fails its checksum. Check the last character.")
    if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", v.ifsc.strip().upper()):
        raise HTTPException(400, "IFSC must be 11 characters, like HDFC0001234.")
    if not re.fullmatch(r"\d{6,18}", v.bank_account.strip()):
        raise HTTPException(400, "Bank account must be 6 to 18 digits.")
    with Session(engine) as s:
        existing = s.exec(select(Vendor)).all()
        if any(e.gstin == gstin for e in existing):
            raise HTTPException(409, "A vendor with this GSTIN is already in the master.")
        n = max([int(e.vendor_id[1:]) for e in existing if e.vendor_id[1:].isdigit()] + [0]) + 1
        vendor = Vendor(vendor_id=f"V{n:03d}", legal_name=name, aliases=v.aliases.strip(), state_code=gstin[:2],
                        gstin=gstin, pan=gstin[2:12], address=v.address.strip(), bank_account=v.bank_account.strip(),
                        ifsc=v.ifsc.strip().upper(), status="approved", payment_terms_days=max(0, v.payment_terms_days))
        s.add(vendor)
        s.commit()
        s.refresh(vendor)
        return vendor.model_dump()


class NewLine(BaseModel):
    description: str
    qty: float = Field(gt=0)
    uom: str = "Nos"
    unit_price: float = Field(ge=0)
    tax_rate: float = 18
    item_code: str = ""


class NewPO(BaseModel):
    vendor_id: str
    po_number: str = ""
    lines: list[NewLine]


@router.post("/purchase_orders")
def add_po(p: NewPO):
    if not p.lines:
        raise HTTPException(400, "Add at least one line.")
    with Session(engine) as s:
        if not s.get(Vendor, p.vendor_id):
            raise HTTPException(400, "Pick a vendor from the master.")
        po_no = p.po_number.strip().upper().replace(" ", "-")
        if not po_no:
            nums = [int(x.po_number.split("-")[-1]) for x in s.exec(select(PurchaseOrder)).all()
                    if x.po_number.split("-")[-1].isdigit()]
            po_no = f"PO-{max(nums + [1000]) + 1}"
        if s.get(PurchaseOrder, po_no):
            raise HTTPException(409, f"{po_no} already exists.")
        subtotal = round(sum(l.qty * l.unit_price for l in p.lines), 2)
        tax = round(sum(l.qty * l.unit_price * l.tax_rate / 100 for l in p.lines), 2)
        s.add(PurchaseOrder(po_number=po_no, vendor_id=p.vendor_id, po_date=datetime.now().date().isoformat(),
                            currency="INR", subtotal=subtotal, tax=tax, total_amount=round(subtotal + tax, 2),
                            status="open"))
        for i, l in enumerate(p.lines, 1):
            s.add(POLine(po_number=po_no, line_no=i, item_code=l.item_code or f"ITEM-{i}",
                         description=l.description.strip(), qty=l.qty, uom=l.uom or "Nos",
                         unit_price=l.unit_price, tax_rate=l.tax_rate))
        s.commit()
    return {"po_number": po_no, "subtotal": subtotal, "tax": tax, "total": round(subtotal + tax, 2)}


# ---------------------------------------------------------------- 6. partial approval
def _over_billed_lines(run_id: int):
    """The cumulative-quantity check's rows for a run, with how much of each line can still be approved."""
    with Session(engine) as s:
        steps = s.exec(select(RunStep).where(RunStep.run_id == run_id)).all()
    for st in steps:
        for r in json.loads(st.detail_json).get("rules", []):
            if r.get("id") == "R10":
                rows = r.get("evidence", {}).get("lines", [])
                out = []
                for row in rows:
                    left = max(row["po_qty"] - row["already_billed"], 0)
                    out.append({**row, "approvable": min(row["qty"], left)})
                return out
    return []


@router.get("/runs/{run_id}/partial")
def partial_preview(run_id: int):
    """What a partial approval would approve: each line up to what is still open on the PO."""
    with Session(engine) as s:
        run = s.get(Run, run_id)
        inv = s.exec(select(InvoiceRecord).where(InvoiceRecord.run_id == run_id)).first()
    if not run or not inv:
        raise HTTPException(404, "Run not found")
    lines = _over_billed_lines(run_id)
    over = [l for l in lines if l["approvable"] < l["qty"]]
    if run.decision != "Hold for review" or not over:
        return {"available": False}
    tax_factor = (inv.total / inv.subtotal) if inv.total and inv.subtotal else 1.18
    held_back = sum((l["qty"] - l["approvable"]) * l["unit_price"] for l in lines) * tax_factor
    total = inv.total or 0
    return {"available": True, "lines": lines, "approve_amount": round(total - held_back, 2),
            "query_amount": round(held_back, 2), "total": total}


class Partial(BaseModel):
    note: str
    reviewer: str = "AP reviewer"


@router.post("/runs/{run_id}/approve_partial")
def approve_partial(run_id: int, body: Partial):
    from .main import get_run
    if not body.note.strip():
        raise HTTPException(400, "Add a short note explaining the decision")
    pv = partial_preview(run_id)
    if not pv["available"]:
        raise HTTPException(409, "Partial approval applies only to held invoices that bill more than is left on the PO.")
    with Session(engine) as s:
        run = s.get(Run, run_id)
        inv = s.exec(select(InvoiceRecord).where(InvoiceRecord.run_id == run_id)).first()
        run.decision = "Approve with note"
        run.reviewed_by, run.reviewed_at = body.reviewer, datetime.now(timezone.utc)
        parts = [f"{l['approvable']:g} of {l['qty']:g} {l['po_desc']}" for l in pv["lines"] if l["approvable"] < l["qty"]]
        run.review_note = f"{body.note.strip()} (Approved in part: {'; '.join(parts)}.)"
        run.approved_amount = pv["approve_amount"]
        inv.decision = "Approve with note"   # counts against the PO, but only for the approved quantity
        inv.consumption_json = json.dumps({str(l["po_line"]): l["approvable"] for l in pv["lines"]})
        s.add(run)
        s.add(inv)
        s.commit()
    audit(run_id, body.reviewer, "approved",
          f"Approved in part: {pv['approve_amount']:,.2f} now, {pv['query_amount']:,.2f} queried with the vendor. "
          f"{body.note.strip()}")
    return get_run(run_id)


# ---------------------------------------------------------------- 7. what reviewers' decisions suggest
RULE_SETTING = {
    "R10": ("price_tolerance_pct", "price tolerance", lambda v: round(v + 1, 1), "%"),
    "R12": ("price_tolerance_pct", "price tolerance", lambda v: round(v + 1, 1), "%"),
    "R2": ("confidence_floor", "confidence needed to skip review", lambda v: round(max(v - 0.05, 0.5), 2), ""),
    "R8": ("duplicate_window_days", "duplicate date window", lambda v: max(int(v) - 2, 1), " days"),
}
RULE_NAME = {"R0": "Hard-to-read invoice", "R1": "Required fields", "R2": "Reading confidence", "R3": "Arithmetic",
             "R4": "GST", "R4b": "Foreign currency", "R5": "Vendor", "R6": "Bank account", "R7": "Exact duplicate",
             "R8": "Possible duplicate", "R9": "Purchase order", "R10": "Line prices", "R11": "Quantity over the PO",
             "R12": "Total vs PO"}


@router.get("/insights")
def insights():
    """For each rule that held invoices: how often a person agreed (rejected) or overrode it (approved)."""
    with Session(engine) as s:
        held = s.exec(select(Run).where(Run.system_decision == "Hold for review")).all()
        steps = s.exec(select(RunStep).where(RunStep.stage == "decide")).all()
    drivers = {st.run_id: [d["id"] for d in json.loads(st.detail_json).get("drivers", [])] for st in steps}
    stats: dict = {}
    for r in held:
        for rid in drivers.get(r.id, [])[:1]:   # the main reason it was held
            x = stats.setdefault(rid, {"rule": rid, "name": RULE_NAME.get(rid, rid), "held": 0, "approved": 0,
                                       "rejected": 0, "waiting": 0})
            x["held"] += 1
            if r.decision == "Reject":
                x["rejected"] += 1
            elif r.decision and r.decision.startswith("Approve"):
                x["approved"] += 1
            else:
                x["waiting"] += 1
    out = []
    for x in sorted(stats.values(), key=lambda x: -x["held"]):
        decided = x["approved"] + x["rejected"]
        x["override_rate"] = round(x["approved"] / decided, 2) if decided else None
        x["suggestion"] = None
        if x["rule"] in RULE_SETTING and decided >= 2 and x["approved"] / decided >= 0.6:
            key, label, nxt, unit = RULE_SETTING[x["rule"]]
            cur = config.SETTINGS[key]
            x["suggestion"] = {"setting": key, "from": cur, "to": nxt(cur),
                               "text": f"Reviewers approved {x['approved']} of {decided} invoices held for this. "
                                       f"Consider changing the {label} from {cur:g}{unit} to {nxt(cur):g}{unit}."}
        elif x["rule"] in ("R6", "R7", "R5") and x["approved"]:
            x["note"] = "This is a fraud or compliance check; overrides here should stay rare and always be noted."
        out.append(x)
    reviewed = sum(1 for r in held if r.reviewed_by)
    return {"held": len(held), "reviewed": reviewed, "rules": out}
