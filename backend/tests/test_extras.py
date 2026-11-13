"""Exports, master data, partial approval, due dates, time saved and reviewer insights."""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DB_PATH", str(BACKEND / "test_invoice_agent.db"))
os.environ.setdefault("EXTRACTOR", "local")

import shutil  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.db import reset_and_seed  # noqa: E402
from app.main import app  # noqa: E402
from app.pipeline import create_run, execute  # noqa: E402


@pytest.fixture(scope="module")
def ids():
    config.SETTINGS["demo_pacing_ms"] = 0
    reset_and_seed()
    out, files = {}, []
    for f in ("01_happy_clean.pdf", "03_split_po_part1.pdf", "04_split_po_part2_over.pdf", "07_bank_changed.pdf"):
        dest = config.UPLOAD_DIR / f"extras_{f}"
        shutil.copy(config.SAMPLES_DIR / f, dest)
        run = create_run(f, dest)
        execute(run.id)
        out[f] = run.id
        files.append(dest)
    yield out
    for p in files:
        p.unlink(missing_ok=True)


c = TestClient(app)


def test_partial_approval(ids):
    r4 = ids["04_split_po_part2_over.pdf"]
    pv = c.get(f"/api/runs/{r4}/partial").json()
    assert pv["available"] and pv["lines"][0]["approvable"] == 40
    assert pv["approve_amount"] + pv["query_amount"] == pytest.approx(pv["total"])
    body = c.post(f"/api/runs/{r4}/approve_partial", json={"note": "Agreed 40 with vendor", "reviewer": "Asha"}).json()
    assert body["run"]["decision"] == "Approve with note" and body["run"]["approved_amount"] == pv["approve_amount"]
    # the bank-change hold is not an over-billing case
    assert c.get(f"/api/runs/{ids['07_bank_changed.pdf']}/partial").json()["available"] is False


def test_due_dates_time_saved_and_csv(ids):
    rows = {r["file_name"]: r for r in c.get("/api/runs").json()}
    assert rows["01_happy_clean.pdf"]["due_date"] and rows["01_happy_clean.pdf"]["terms_days"] == 30
    stats = c.get("/api/stats").json()
    assert stats["minutes_saved"] == 2 * config.SETTINGS["manual_minutes_per_invoice"]
    csv_text = c.get("/api/runs.csv").text
    assert csv_text.splitlines()[0].startswith("id,file_name") and "Shreeji Steel Traders" in csv_text
    assert "attachment" in c.get(f"/api/runs/{ids['01_happy_clean.pdf']}/decision.json").headers["content-disposition"]


def test_master_add_vendor_and_po():
    bad = c.post("/api/vendors", json={"legal_name": "X", "gstin": "27AAKFS1234L1ZA", "bank_account": "1234567",
                                       "ifsc": "HDFC0001234"})
    assert bad.status_code == 400
    po = c.post("/api/purchase_orders", json={"vendor_id": "V001", "lines": [
        {"description": "Widget", "qty": 10, "unit_price": 100, "tax_rate": 18}]}).json()
    assert po["total"] == 1180
    assert any(p["po_number"] == po["po_number"] for p in c.get("/api/master/full").json()["purchase_orders"])


def test_insights_counts_reviewer_overrides(ids):
    c.post(f"/api/runs/{ids['07_bank_changed.pdf']}/review", json={"action": "approve", "note": "Called vendor"})
    rules = {r["rule"]: r for r in c.get("/api/insights").json()["rules"]}
    assert rules["R6"]["approved"] == 1 and "fraud" in rules["R6"]["note"]
