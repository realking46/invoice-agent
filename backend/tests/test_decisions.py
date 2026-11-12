"""End-to-end: every test invoice, run in demo order, must get its expected decision.
Run from backend/:  pytest -q        (uses local extraction unless EXTRACTOR=llm)"""
import csv
import os
import shutil
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DB_PATH", str(BACKEND / "test_invoice_agent.db"))
os.environ.setdefault("EXTRACTOR", "local")

from app import config, rules  # noqa: E402
from app.db import reset_and_seed  # noqa: E402
from app.pipeline import create_run, execute  # noqa: E402
from sqlmodel import Session  # noqa: E402
from app.db import Run, engine  # noqa: E402

EXPECTED = list(csv.DictReader(open(config.REPO_DIR / "data" / "expected_decisions.csv")))


@pytest.fixture(scope="module")
def results():
    config.SETTINGS["demo_pacing_ms"] = 0
    reset_and_seed()
    out = {}
    for row in EXPECTED:  # file order IS demo order: 03 before 04, 01 before 05
        dest = config.UPLOAD_DIR / f"test_{row['file']}"
        shutil.copy(config.SAMPLES_DIR / row["file"], dest)
        run = create_run(row["file"], dest)
        execute(run.id)
        with Session(engine) as s:
            out[row["file"]] = s.get(Run, run.id)
        dest.unlink()
    return out


@pytest.mark.parametrize("row", EXPECTED, ids=[r["file"] for r in EXPECTED])
def test_expected_decision(results, row):
    run = results[row["file"]]
    assert run.status == "done", run.reason_summary
    assert run.decision == row["expected_decision"], f"{run.decision}: {run.reason_summary}"


def test_reasons_are_specific(results):
    assert "15 over" in results["04_split_po_part2_over.pdf"].reason_summary
    assert "INV-0042" in results["05_duplicate_renumbered.pdf"].reason_summary
    assert "PO-1007" in results["06_scanned_no_po.pdf"].reason_summary or \
        "low confidence" in results["06_scanned_no_po.pdf"].reason_summary
    assert "…8890" in results["07_bank_changed.pdf"].reason_summary


@pytest.mark.parametrize("a,b", [("INV-0042", "INV 42"), ("inv/042", "INV42"), ("VF-2611-0087", "VF 2611 87")])
def test_invoice_number_normalisation(a, b):
    assert rules.normalise_invoice_no(a) == rules.normalise_invoice_no(b)


def test_different_numbers_stay_different():
    assert rules.normalise_invoice_no("INV-0042") != rules.normalise_invoice_no("INV-0420")


def test_tolerance_is_lower_of_pct_and_cap():
    assert rules.tolerance(10_000) == 200      # 2 % of 10,000
    assert rules.tolerance(100_000) == 500     # capped at ₹500


def test_reviewer_can_approve_a_held_invoice(results):
    from app.main import Review, review
    out = review(results["07_bank_changed.pdf"].id, Review(action="approve", note="Called vendor on file; change confirmed"))
    assert out["run"]["decision"] == "Approve"
    assert out["run"]["system_decision"] == "Hold for review"
    assert [a["action"] for a in out["audit"]] == ["received", "decided", "approved"]


def test_only_held_invoices_can_be_reviewed(results):
    from fastapi import HTTPException
    from app.main import Review, review
    with pytest.raises(HTTPException) as e:
        review(results["01_happy_clean.pdf"].id, Review(action="reject", note="test"))
    assert e.value.status_code == 409
