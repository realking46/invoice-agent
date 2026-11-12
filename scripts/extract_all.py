"""Day-2 check: extract all 8 test invoices and score them against data/ground_truth.json.

    python scripts/extract_all.py            # auto mode (LLM if ANTHROPIC_API_KEY is set)
    EXTRACTOR=local python scripts/extract_all.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import config  # noqa: E402
from app.extract import extract  # noqa: E402

truth = json.loads((ROOT / "data" / "ground_truth.json").read_text())
FIELDS = ["vendor_gstin", "invoice_number", "invoice_date", "po_reference", "subtotal", "tax_total", "total",
          "bank_account", "ifsc"]

print(f"mode = {config.extractor_mode()}, provider = {config.provider()}, model = {config.model_name()}\n")
grand_ok = grand_n = fallbacks = 0
for f in sorted(truth):
    t0 = time.time()
    r = extract(config.SAMPLES_DIR / f)
    d, exp = r.data, truth[f]
    ok = n = 0
    bad = []
    for k in FIELDS:
        got, want = getattr(d, k), exp[k]
        n += 1
        if (got == want) or (isinstance(want, float) and got is not None and abs(got - want) < 0.01):
            ok += 1
        else:
            bad.append(f"{k}: got {got!r} want {want!r} (conf {d.confidence.get(k)})")
    lines_ok = len(d.line_items) == exp["line_count"]
    grand_ok += ok
    grand_n += n
    reader = (r.provider or "llm") + (" (cached)" if r.cached else "") if r.mode == "llm" else "local"
    print(f"{f:30} route={r.route:4} read by {reader:14} {ok}/{n} fields  lines {len(d.line_items)}/{exp['line_count']}"
          f"{'' if lines_ok else ' !!'}  {time.time() - t0:.1f}s")
    if r.fallback_reason:
        print(f"     ! AI reader failed, fell back to local: {r.fallback_reason}")
        fallbacks += 1
    for b in bad:
        print("     -", b)
    if r.missing_fields:
        print("     missing:", r.missing_fields)
    if r.unreadable_fields:
        print("     unreadable:", r.unreadable_fields)
    if r.low_confidence_fields:
        print("     low confidence:", r.low_confidence_fields)
    if d.notes:
        print("     notes:", d.notes)
print(f"\nfield accuracy: {grand_ok}/{grand_n} = {grand_ok / grand_n:.0%}")
if fallbacks:
    print(f"WARNING: {fallbacks} file(s) were read locally because the AI reader failed. Fix that before trusting LLM mode.")