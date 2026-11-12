"""FastAPI app.  Run:  cd backend && uvicorn app.main:app --reload"""
import asyncio
import json
import os
import shutil
import uuid

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from . import config
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import func

from .db import (AuditEvent, InvoiceRecord, PurchaseOrder, Run, RunStep, Vendor, audit, engine, ensure_seeded,
                 reset_and_seed)
from .pipeline import STAGES, bus, create_run, execute

app = FastAPI(title="Invoice Agent", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_PASSWORD = os.getenv("APP_PASSWORD")


@app.middleware("http")
async def password_gate(request, call_next):
    """Optional shared password (HTTP Basic, any username) so a public URL can't burn API credits.
    /api/health stays open for the host's health check."""
    if not _PASSWORD or request.url.path == "/api/health":
        return await call_next(request)
    import base64
    import secrets
    auth = request.headers.get("authorization", "")
    if auth.startswith("Basic "):
        try:
            _, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
            if secrets.compare_digest(pw, _PASSWORD):
                return await call_next(request)
        except Exception:
            pass
    return Response("Password required", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Invoice agent"'})


@app.on_event("startup")
def startup():
    ensure_seeded()


@app.get("/api/health")
def health():
    return {"ok": True, "extractor": config.extractor_mode(), "provider": config.provider(),
            "model": config.model_name()}


SAMPLE_LABELS = {
    "01_happy_clean.pdf": ("Clean invoice", "Digital PDF that matches its purchase order line for line"),
    "02_happy_tolerance.pdf": ("Small extra charge", "Adds a freight line that is not on the purchase order"),
    "03_split_po_part1.pdf": ("Partial delivery", "Bills 60 of 100 boxes ordered on one purchase order"),
    "04_split_po_part2_over.pdf": ("Second partial delivery", "Bills 55 more boxes on the same order; run after the partial delivery"),
    "05_duplicate_renumbered.pdf": ("Re-sent invoice", "Same invoice as the clean one, renumbered and redated"),
    "06_scanned_no_po.pdf": ("Scanned, no order number", "Photocopied image with bundled items and no purchase order cited"),
    "07_bank_changed.pdf": ("New bank account", "Everything matches except the bank account to pay"),
    "08_missing_fields.pdf": ("Incomplete invoice", "No invoice number and no grand total"),
}


@app.get("/api/samples")
def samples():
    out = []
    for p in sorted(config.SAMPLES_DIR.glob("*.pdf")):
        title, desc = SAMPLE_LABELS.get(p.name, (p.stem, ""))
        out.append({"file": p.name, "title": title, "description": desc})
    return out


def _start(file_name, path, background: BackgroundTasks):
    run = create_run(file_name, path)
    background.add_task(execute, run.id)
    return {"run_id": run.id, "stages": [{"key": k, "label": l} for k, l in STAGES]}


@app.post("/api/runs")
def upload(background: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF invoice")
    dest = config.UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return _start(file.filename, dest, background)


@app.post("/api/runs/sample/{name}")
def run_sample(name: str, background: BackgroundTasks):
    src = config.SAMPLES_DIR / name
    if not src.exists() or src.suffix != ".pdf":
        raise HTTPException(404, "Unknown sample")
    dest = config.UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{name}"
    shutil.copy(src, dest)
    return _start(name, dest, background)


def _run_rows(s: Session) -> list[dict]:
    runs = s.exec(select(Run).order_by(Run.id.desc())).all()
    invs = {i.run_id: i for i in s.exec(select(InvoiceRecord)).all()}
    vendors = {v.vendor_id: v.legal_name for v in s.exec(select(Vendor)).all()}
    ms = dict(s.exec(select(RunStep.run_id, func.sum(RunStep.duration_ms)).group_by(RunStep.run_id)).all())
    rows = []
    for r in runs:
        inv = invs.get(r.id)
        extracted = json.loads(inv.extracted_json) if inv else {}
        rows.append({**r.model_dump(exclude={"file_path"}),
                     "vendor": vendors.get(getattr(inv, "vendor_id", None)) or extracted.get("data", {}).get("vendor_name"),
                     "invoice_no": getattr(inv, "invoice_no", None),
                     "total": getattr(inv, "total", None) if inv and inv.total is not None else (
                         (inv.subtotal or 0) + (inv.tax or 0) if inv and inv.subtotal is not None else None),
                     "po_number": getattr(inv, "po_number", None),
                     "currency": (extracted.get("data", {}).get("currency") or "INR").upper(),
                     "po_inferred": bool(inv and inv.po_number and not extracted.get("data", {}).get("po_reference")),
                     "processing_ms": ms.get(r.id, 0)})
    return rows


@app.get("/api/runs")
def list_runs():
    with Session(engine) as s:
        return _run_rows(s)


def _other_currency_totals(rows) -> dict:
    """Non-INR invoices are summed per currency and shown beside the INR total, never converted."""
    out: dict = {}
    for r in rows:
        cur = r["currency"] or "INR"
        if cur != "INR" and r["total"]:
            out[cur] = round(out.get(cur, 0) + r["total"], 2)
    return out


@app.get("/api/stats")
def stats():
    with Session(engine) as s:
        rows = [r for r in _run_rows(s) if r["status"] == "done"]
    by = {k: 0 for k in ("Approve", "Approve with note", "Hold for review", "Reject")}
    for r in rows:
        by[r["decision"]] = by.get(r["decision"], 0) + 1
    auto = [r for r in rows if r["system_decision"] in ("Approve", "Approve with note")]
    return {
        "invoices": len(rows),
        "value": round(sum(r["total"] or 0 for r in rows if (r["currency"] or "INR") == "INR"), 2),  # INR only: no FX
        "other_currencies": _other_currency_totals(rows),
        "by_decision": by,
        "waiting_review": sum(1 for r in rows if r["decision"] == "Hold for review"),
        "reviewed": sum(1 for r in rows if r["reviewed_by"]),
        "auto_decided_pct": round(100 * sum(1 for r in rows if r["system_decision"] != "Hold for review") / len(rows))
        if rows else 0,
        "auto_approved": len(auto),
        "avg_processing_ms": round(sum(r["processing_ms"] for r in rows) / len(rows)) if rows else 0,
    }


class Review(BaseModel):
    action: str          # approve | reject
    note: str
    reviewer: str = "AP reviewer"


@app.post("/api/runs/{run_id}/review")
def review(run_id: int, body: Review):
    """A person resolves a held invoice. The rules' original decision is kept; every change is audited."""
    if body.action not in ("approve", "reject"):
        raise HTTPException(400, "action must be approve or reject")
    if not body.note.strip():
        raise HTTPException(400, "Add a short note explaining the decision")
    with Session(engine) as s:
        run = s.get(Run, run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        if run.decision != "Hold for review":
            raise HTTPException(409, f"Only held invoices can be reviewed; this one is '{run.decision}'")
        new = "Approve" if body.action == "approve" else "Reject"
        run.decision, run.reviewed_by, run.review_note = new, body.reviewer, body.note.strip()
        run.reviewed_at = datetime.now(timezone.utc)
        inv = s.exec(select(InvoiceRecord).where(InvoiceRecord.run_id == run_id)).first()
        if inv:
            inv.decision = new  # approved now counts against the PO; rejected no longer counts as received
            s.add(inv)
        s.add(run)
        s.commit()
    audit(run_id, body.reviewer, "approved" if new == "Approve" else "rejected", body.note.strip())
    return get_run(run_id)


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    with Session(engine) as s:
        run = s.get(Run, run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        steps = s.exec(select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.order)).all()
        inv = s.exec(select(InvoiceRecord).where(InvoiceRecord.run_id == run_id)).first()
        trail = s.exec(select(AuditEvent).where(AuditEvent.run_id == run_id).order_by(AuditEvent.id)).all()
        return {"run": run.model_dump(exclude={"file_path"}), "audit": [a.model_dump() for a in trail],
                "steps": [{**st.model_dump(exclude={"detail_json"}), "detail": json.loads(st.detail_json)}
                          for st in steps],
                "invoice": inv.model_dump(exclude={"extracted_json"}) if inv else None}


@app.get("/api/runs/{run_id}/file")
def run_file(run_id: int):
    with Session(engine) as s:
        run = s.get(Run, run_id)
        if not run:
            raise HTTPException(404)
        return FileResponse(run.file_path, media_type="application/pdf", filename=run.file_name)


@app.get("/api/runs/{run_id}/page/{n}.png")
def run_page(run_id: int, n: int = 1):
    import fitz
    with Session(engine) as s:
        run = s.get(Run, run_id)
    if not run:
        raise HTTPException(404)
    with fitz.open(run.file_path) as doc:
        if not 1 <= n <= len(doc):
            raise HTTPException(404)
        png = doc[n - 1].get_pixmap(dpi=110).tobytes("png")
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/runs/{run_id}/stream")
async def stream(run_id: int):
    """Server-Sent Events: replays everything so far, then pushes new stage events as they happen."""
    async def gen():
        idx, idle = 0, 0
        while True:
            events = bus.since(run_id, idx)
            for ev in events:
                yield f"data: {json.dumps(ev, default=str)}\n\n"
                if ev["type"] == "run_finished":
                    return
            idx += len(events)
            idle = 0 if events else idle + 1
            if idle > 1200:  # ~3 min with no events
                return
            await asyncio.sleep(0.15)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/master")
def master_data():
    with Session(engine) as s:
        return {"vendors": s.exec(select(Vendor)).all(), "purchase_orders": s.exec(select(PurchaseOrder)).all()}


@app.get("/api/config")
def get_config():
    return config.SETTINGS


@app.put("/api/config")
def put_config(update: dict):
    for k, v in update.items():
        if k in config.SETTINGS:
            config.SETTINGS[k] = type(config.SETTINGS[k])(v)
    return config.SETTINGS


@app.post("/api/reset")
def reset():
    reset_and_seed()
    bus.clear()
    for p in config.UPLOAD_DIR.glob("*"):
        p.unlink()
    return {"ok": True}



@app.post("/api/runs/samples/all")
def run_all_samples(background: BackgroundTasks):
    """Demo helper: reset, then process every prepared sample in order (order matters for split POs and duplicates)."""
    reset()
    ids = []
    for src in sorted(config.SAMPLES_DIR.glob("*.pdf")):
        dest = config.UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{src.name}"
        shutil.copy(src, dest)
        ids.append(create_run(src.name, dest).id)

    def in_order():
        for i in ids:
            execute(i)

    background.add_task(in_order)
    return {"run_ids": ids}


def _indian(x: float) -> str:
    whole, frac = f"{abs(x):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join(([head] if head else []) + parts + [tail])
    return f"{whole}.{frac}"


@app.get("/api/runs/{run_id}/highlights")
def highlights(run_id: int):
    """Where on page 1 the fields behind the decision are printed, as fractions of the page.
    Works on PDFs with a text layer; a scanned image has nothing to search, so it returns no boxes."""
    import fitz
    with Session(engine) as s:
        run = s.get(Run, run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        steps = s.exec(select(RunStep).where(RunStep.run_id == run_id)).all()
        inv = s.exec(select(InvoiceRecord).where(InvoiceRecord.run_id == run_id)).first()
    details = {st.stage: json.loads(st.detail_json) for st in steps}
    drivers = [d["id"] for d in details.get("decide", {}).get("drivers", [])]
    rule = {r["id"]: r for d in details.values() for r in d.get("rules", [])}
    data = json.loads(inv.extracted_json).get("data", {}) if inv else {}
    boxes = []
    if not os.path.exists(run.file_path):
        return {"page": 1, "boxes": boxes}
    with fitz.open(run.file_path) as doc:
        page = doc[0]
        W, H = page.rect.width, page.rect.height

        def find(text):
            text = (text or "").strip()
            for probe in (text, text[:28]):
                if len(probe) >= 3:
                    hits = page.search_for(probe)
                    if hits:
                        return hits[0]
            return None

        def add(rect, label, rid, full_row=False):
            if rect is None:
                return
            x0, x1 = (rect.x0, W * 0.93) if full_row else (rect.x0, rect.x1)
            boxes.append({"x": round((x0 - 3) / W, 4), "y": round((rect.y0 - 2) / H, 4),
                          "w": round((x1 - x0 + 6) / W, 4), "h": round((rect.y1 - rect.y0 + 4) / H, 4),
                          "label": label, "rule": rid})

        for rid in drivers:
            ev = rule.get(rid, {}).get("evidence", {})
            if rid == "R6":
                add(find(data.get("bank_account")), "Not the bank account on file", rid)
                add(find(data.get("ifsc")), "Not the IFSC on file", rid)
            elif rid in ("R7", "R8"):
                add(find(data.get("invoice_number")), "Matches an earlier invoice", rid)
            elif rid in ("R10", "R11"):
                for ln in ev.get("lines", []):
                    over = ln["qty"] + ln["already_billed"] > ln["po_qty"]
                    price = abs(ln["unit_price"] - ln["po_unit_price"]) > 0.001
                    if (rid == "R11" and over) or (rid == "R10" and price):
                        add(find(ln["invoice_line"]), "More than is left on the PO" if rid == "R11"
                            else "Price differs from the PO", rid, full_row=True)
            elif rid == "R12":
                extras = ev.get("extra_lines", [])
                for e in extras:
                    add(find(e), "Not on the purchase order", rid, full_row=True)
                if not extras and data.get("total") is not None:
                    add(find(_indian(data["total"])) or find(f"{data['total']:,.2f}"), "Differs from the PO value", rid)
            elif rid == "R5":
                add(find(data.get("vendor_name")), "Vendor not approved", rid)
            elif rid == "R3" and data.get("total") is not None:
                add(find(_indian(data["total"])), "Figures don't add up", rid)
    return {"page": 1, "boxes": boxes}

# Serve the built frontend (frontend/dist) at / when it exists
_dist = config.REPO_DIR / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
