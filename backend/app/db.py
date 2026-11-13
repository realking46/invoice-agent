"""SQLite models + seeding from data/seed/*.csv."""
import csv
import json
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Session, SQLModel, create_engine, delete, select

from . import config

engine = create_engine(f"sqlite:///{config.DB_PATH}", connect_args={"check_same_thread": False})


def now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- reference data (procurement system)
class Vendor(SQLModel, table=True):
    vendor_id: str = Field(primary_key=True)
    legal_name: str
    aliases: str = ""          # pipe-separated
    state_code: str
    gstin: str
    pan: str
    address: str
    bank_account: str
    ifsc: str
    status: str                # approved | blocked
    payment_terms_days: int


class PurchaseOrder(SQLModel, table=True):
    po_number: str = Field(primary_key=True)
    vendor_id: str = Field(foreign_key="vendor.vendor_id")
    po_date: str
    currency: str
    subtotal: float
    tax: float
    total_amount: float
    status: str


class POLine(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    po_number: str = Field(foreign_key="purchaseorder.po_number")
    line_no: int
    item_code: str
    description: str
    qty: float
    uom: str
    unit_price: float
    tax_rate: float


# ---------------------------------------------------------------- run data (written by the process)
class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    file_name: str
    file_path: str
    file_hash: str
    started_at: datetime = Field(default_factory=now)
    finished_at: Optional[datetime] = None
    status: str = "queued"     # queued | running | done | error
    decision: Optional[str] = None
    confidence: Optional[float] = None
    reason_summary: Optional[str] = None
    extraction_mode: Optional[str] = None
    route: Optional[str] = None
    system_decision: Optional[str] = None   # what the rules decided; `decision` may later be changed by a reviewer
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    approved_amount: Optional[float] = None   # set when a reviewer approves only part of the invoice


class RunStep(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    order: int
    stage: str
    status: str                # running | pass | warn | fail | skipped | error
    summary: str = ""
    duration_ms: int = 0
    detail_json: str = "{}"


class InvoiceRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    vendor_id: Optional[str] = None
    invoice_no: Optional[str] = None
    invoice_no_normalised: Optional[str] = None
    invoice_date: Optional[str] = None
    po_number: Optional[str] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    decision: Optional[str] = None
    consumption_json: str = "{}"   # {po_line_no: qty billed by this invoice} for cumulative PO checks
    extracted_json: str = "{}"


class AuditEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    at: datetime = Field(default_factory=now)
    actor: str                 # "system" or the reviewer's name
    action: str                # received | decided | approved | rejected
    detail: str = ""


def audit(run_id: int, actor: str, action: str, detail: str = ""):
    with Session(engine) as s:
        s.add(AuditEvent(run_id=run_id, actor=actor, action=action, detail=detail))
        s.commit()


def init_db():
    SQLModel.metadata.create_all(engine)


def reset_and_seed():
    """Wipe everything and reload the procurement data. Used before every demo."""
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        with open(config.SEED_DIR / "vendors.csv") as f:
            for r in csv.DictReader(f):
                r["payment_terms_days"] = int(r["payment_terms_days"])
                s.add(Vendor(**r))
        with open(config.SEED_DIR / "purchase_orders.csv") as f:
            for r in csv.DictReader(f):
                for k in ("subtotal", "tax", "total_amount"):
                    r[k] = float(r[k])
                s.add(PurchaseOrder(**r))
        with open(config.SEED_DIR / "po_lines.csv") as f:
            for r in csv.DictReader(f):
                s.add(POLine(po_number=r["po_number"], line_no=int(r["line_no"]), item_code=r["item_code"],
                             description=r["description"], qty=float(r["qty"]), uom=r["uom"],
                             unit_price=float(r["unit_price"]), tax_rate=float(r["tax_rate"])))
        s.commit()


def _schema_current() -> bool:
    """An older database file lacks newer columns; it is rebuilt from the seed data (demo data only)."""
    from sqlalchemy import inspect
    insp = inspect(engine)
    if not insp.has_table("run"):
        return True
    cols = {c["name"] for c in insp.get_columns("run")}
    return {"approved_amount"} <= cols


def ensure_seeded():
    if not _schema_current():
        SQLModel.metadata.drop_all(engine)
    init_db()
    with Session(engine) as s:
        if not s.exec(select(Vendor)).first():
            reset_and_seed()


def dumps(obj) -> str:
    return json.dumps(obj, default=str)
