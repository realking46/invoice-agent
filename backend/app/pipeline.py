"""The pipeline. Each stage is a function that returns (status, summary, detail).
The runner times it, writes a RunStep row, and publishes start/finish events for the live view.

Stages: ingest -> classify -> extract -> validate -> vendor -> duplicate -> PO match -> decide -> output."""
import hashlib
import threading
import time
import traceback
from datetime import datetime, timezone

from sqlmodel import Session, select

from . import config, rules
from .db import InvoiceRecord, Run, RunStep, audit, dumps, engine
from .extract import extract
from .extract.pdf_utils import classify

STAGES = [
    ("ingest", "Ingest"),
    ("classify", "Classify"),
    ("extract", "Extract"),
    ("validate", "Validate"),
    ("vendor", "Vendor and bank check"),
    ("duplicate", "Duplicate check"),
    ("po_match", "PO match"),
    ("decide", "Decide"),
    ("output", "Output"),
]


# ---------------------------------------------------------------- event bus (read by the SSE endpoint)
class EventBus:
    def __init__(self):
        self._events: dict[int, list[dict]] = {}
        self._lock = threading.Lock()

    def publish(self, run_id: int, event: dict):
        event = {**event, "ts": datetime.now(timezone.utc).isoformat()}
        with self._lock:
            self._events.setdefault(run_id, []).append(event)

    def clear(self):
        """Called on demo reset: run ids restart at 1, so old events must not be replayed."""
        with self._lock:
            self._events.clear()

    def since(self, run_id: int, idx: int) -> list[dict]:
        with self._lock:
            return list(self._events.get(run_id, [])[idx:])


bus = EventBus()


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- stages
def st_ingest(ctx):
    with Session(engine) as s:
        prior = s.exec(select(Run).where(Run.file_hash == ctx["run"].file_hash, Run.id != ctx["run"].id)).first()
    ctx["same_file_run"] = prior.id if prior else None
    if prior:
        return "warn", f"Identical file already processed (run #{prior.id})", {"duplicate_of_run": prior.id}
    return "pass", "File stored and fingerprinted", {"sha256": ctx["run"].file_hash[:16] + "...",
                                                       "file": ctx["run"].file_name}


def st_classify(ctx):
    info = classify(ctx["path"])
    ctx["route"] = info["route"]
    if info["route"] == "scan":
        return "warn", "Scanned image, no text layer: reading with vision/OCR", \
            {"route": "scan", "chars_per_page": info["chars_per_page"]}
    return "pass", f"Digital PDF with readable text ({sum(info['chars_per_page'])} chars)", \
        {"route": "text", "chars_per_page": info["chars_per_page"]}


def st_extract(ctx):
    run_id = ctx["run"].id
    log: list[str] = []

    def progress(m):
        log.append(m)
        bus.publish(run_id, {"type": "stage_progress", "stage": "extract", "message": m})

    res = extract(ctx["path"], progress=progress)
    ctx["extraction"] = res
    d = res.data
    detail = {
        "mode": res.mode, "route": res.route, "fallback_reason": res.fallback_reason, "cached": res.cached,
        "progress": log,
        "provider": res.provider,
        "fields": {k: getattr(d, k) for k in ["vendor_name", "vendor_gstin", "invoice_number", "invoice_date",
                                              "po_reference", "subtotal", "tax_total", "total", "bank_account",
                                              "ifsc", "notes"]},
        "line_items": [li.model_dump() for li in d.line_items],
        "tax_lines": [t.model_dump() for t in d.tax_lines],
        "confidence": d.confidence, "evidence": d.evidence, "checks": res.checks,
        "missing_fields": res.missing_fields, "unreadable_fields": res.unreadable_fields,
        "low_confidence_fields": res.low_confidence_fields,
    }
    with Session(engine) as s:
        s.add(InvoiceRecord(run_id=ctx["run"].id, invoice_no=d.invoice_number, invoice_date=d.invoice_date,
                            po_number=d.po_reference, subtotal=d.subtotal, tax=d.tax_total, total=d.total,
                            extracted_json=res.model_dump_json()))
        s.commit()
    n_ok = sum(1 for v in d.confidence.values() if v >= config.SETTINGS["confidence_floor"])
    who = (res.provider or "LLM").capitalize()
    how = f"read by {who}" + (", cached" if res.cached else "") if res.mode == "llm" else \
        ("AI reader unavailable, read locally" if res.fallback_reason else "read locally")
    summary = f"{n_ok}/{len(d.confidence)} fields confident, {len(d.line_items)} line items ({how})"
    flagged = res.missing_fields or res.unreadable_fields or res.low_confidence_fields
    return ("warn" if flagged else "pass"), summary, detail


def _rule_stage(results, ctx, pass_summary):
    ctx.setdefault("results", []).extend(results)
    outcome = rules.worst(results)
    lead = next((r.reason for r in results if r.outcome == outcome), None) if outcome else pass_summary
    return rules.stage_status(results), lead, rules.pack(results)


def st_validate(ctx):
    return _rule_stage(rules.validate(ctx["extraction"]), ctx, "Required fields present, numbers add up, tax valid")


def st_vendor(ctx):
    res = rules.vendor_checks(ctx["extraction"].data, ctx)
    v = ctx.get("vendor")
    return _rule_stage(res, ctx, f"{v.legal_name}: approved, bank details match" if v else "")


def st_duplicate(ctx):
    return _rule_stage(rules.duplicate_checks(ctx["extraction"].data, ctx), ctx, "Not a duplicate")


def st_po_match(ctx):
    res = rules.po_checks(ctx["extraction"].data, ctx)
    po = ctx.get("po")
    return _rule_stage(res, ctx, f"Matches {po.po_number}: prices, quantities and total within limits" if po else "")


def st_decide(ctx):
    dec = rules.decide(ctx["results"], ctx)
    ctx["decision"] = dec
    status = {"Approve": "pass", "Approve with note": "note", "Hold for review": "warn", "Reject": "fail"}[dec["decision"]]
    return status, f"{dec['decision']}: {dec['summary']}", dec


def st_output(ctx):
    dec, d = ctx["decision"], ctx["extraction"].data
    act = rules.next_action(dec, ctx["results"], ctx)
    ctx["action"] = act
    v, po = ctx.get("vendor"), ctx.get("po")
    with Session(engine) as s:
        rec = s.exec(select(InvoiceRecord).where(InvoiceRecord.run_id == ctx["run"].id)).first()
        rec.vendor_id = v.vendor_id if v else None
        rec.invoice_no_normalised = rules.normalise_invoice_no(d.invoice_number)
        rec.po_number = po.po_number if po else d.po_reference
        rec.decision = dec["decision"]
        rec.consumption_json = dumps(ctx.get("consumption", {}))
        s.add(rec)
        run = s.get(Run, ctx["run"].id)
        run.decision, run.confidence, run.reason_summary = dec["decision"], dec["confidence"], dec["summary"]
        run.system_decision = dec["decision"]
        s.add(run)
        s.commit()
    audit(ctx["run"].id, "system", "decided", f"{dec['decision']}: {dec['summary']}")
    return "pass", act["action"], {"next_action": act, "vendor": v.legal_name if v else None,
                                   "po": po.po_number if po else None}


STAGE_FUNCS = {"ingest": st_ingest, "classify": st_classify, "extract": st_extract, "validate": st_validate,
               "vendor": st_vendor, "duplicate": st_duplicate, "po_match": st_po_match, "decide": st_decide,
               "output": st_output}
_RUN_LOCK = threading.Lock()  # one invoice at a time: later invoices must see earlier decisions (split POs, duplicates)


# ---------------------------------------------------------------- runner
def _save_step(run_id, order, stage, status, summary, ms, detail):
    with Session(engine) as s:
        s.add(RunStep(run_id=run_id, order=order, stage=stage, status=status, summary=summary,
                      duration_ms=ms, detail_json=dumps(detail)))
        s.commit()


def create_run(file_name: str, path) -> Run:
    with Session(engine) as s:
        run = Run(file_name=file_name, file_path=str(path), file_hash=sha256(path))
        s.add(run)
        s.commit()
        s.refresh(run)
    audit(run.id, "system", "received", file_name)
    return run


def execute(run_id: int):
    with _RUN_LOCK:
        _execute(run_id)


def _execute(run_id: int):
    with Session(engine) as s:
        run = s.get(Run, run_id)
        run.status = "running"
        s.add(run)
        s.commit()
        s.refresh(run)
    ctx = {"run": run, "path": run.file_path}
    bus.publish(run_id, {"type": "run_started", "stages": [{"key": k, "label": l} for k, l in STAGES]})
    try:
        for order, (key, label) in enumerate(STAGES, 1):
            bus.publish(run_id, {"type": "stage_started", "stage": key, "label": label})
            t0 = time.perf_counter()
            status, summary, detail = STAGE_FUNCS[key](ctx)
            ms = int((time.perf_counter() - t0) * 1000)  # real processing time, shown in the UI
            pace = config.SETTINGS["demo_pacing_ms"] / 1000 - (time.perf_counter() - t0)
            if pace > 0:  # demo pacing only delays the event; recorded duration stays real
                time.sleep(pace)
            _save_step(run_id, order, key, status, summary, ms, detail)
            bus.publish(run_id, {"type": "stage_finished", "stage": key, "status": status, "summary": summary,
                                 "duration_ms": ms, "detail": detail})
        with Session(engine) as s:
            run = s.get(Run, run_id)
            run.status = "done"
            run.finished_at = datetime.now(timezone.utc)
            if "extraction" in ctx:
                run.extraction_mode, run.route = ctx["extraction"].mode, ctx["extraction"].route
            s.add(run)
            s.commit()
        bus.publish(run_id, {"type": "run_finished", "status": "done", "decision": ctx.get("decision"),
                             "next_action": ctx.get("action")})
    except Exception as e:  # never leave a run hanging: record the error, the UI shows it
        _save_step(run_id, 99, "error", "error", str(e), 0, {"traceback": traceback.format_exc()[-2000:]})
        with Session(engine) as s:
            run = s.get(Run, run_id)
            run.status, run.reason_summary = "error", f"Processing failed: {e}"
            run.finished_at = datetime.now(timezone.utc)
            s.add(run)
            s.commit()
        bus.publish(run_id, {"type": "run_finished", "status": "error", "error": str(e)})
