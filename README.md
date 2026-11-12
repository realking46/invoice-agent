# Invoice agent: from PDF to decision

Zamp AI Solutions Analyst case study, **PS-1 (Finance / AP)**, by Nishant Singh.

An AP clerk opens each vendor invoice, finds the purchase order, checks the numbers and decides what to do. This process
does that end to end: it takes an invoice PDF (digital or scanned) and returns **Approve, Approve with note, Hold for
review or Reject**, with the reason, the evidence behind every check, and the next step for the right person.

**Design principle: the LLM reads, the rules decide.** The whole stack runs on free tiers (Gemini, Render). Reading messy documents is where a model beats templates.
Deciding whether to pay is where finance teams need rules they can read, test and change.

## What it does

```
PDF ─► Receive ─► Check type ─► Read ─► Validate ─► Vendor & bank ─► Duplicates ─► PO match ─► Decide ─► Route
        hash      text / scan   Gemini   fields,      approved list,   normalised     line price,   most      owner,
                                or OCR   arithmetic,  bank vs master   number,        cumulative    severe    vendor email,
                                         GST                           amount + date  qty, total    wins      audit trail
```

| Scenario (sample) | Decision | Why it matters |
|---|---|---|
| Clean invoice | Approve | Happy path |
| Freight line not on the PO (+₹472) | Approve with note | Tolerance is a setting: ±2 % or ₹500, whichever is lower |
| **EC1** Second partial delivery: 60 + 55 of 100 boxes | Hold | Remembers what was billed before; "approve 40, query 15" |
| **EC2** Same invoice re-sent as "INV 42" | Reject | Normalised numbers catch what exact matching misses |
| **EC3** Scanned, no PO, items bundled | Hold | Infers PO-1007 (0.89) over a decoy PO-1008 (0.46) and asks a person to confirm |
| **EC4** Bank account changed | Hold | One fraud signal outweighs every green check |
| No invoice number or total | Reject | Drafts the request to the vendor |
| Foreign or hard-to-read invoice (non-INR, under half the key fields read) | Hold | Unfamiliar input goes to a person instead of being rejected |

## Try it

The live link is in the submission email. The site has four parts: **Home** (what it does, the hard cases, one-click
sample runs), **Try it** (upload a PDF or pick a sample, plus the review queue), the **live run view** (each stage as it
runs, with the invoice and the fields that drove the decision highlighted) and **History** (totals, decisions, filters,
audit trail). **Rule settings** changes tolerances live.

Locally:

```bash
pip install -r backend/requirements.txt        # plus tesseract-ocr for the local reader
cp .env.example .env                           # add a free GEMINI_API_KEY; without it the local reader is used
cd frontend && npm install && npm run build    # builds the UI into frontend/dist (not committed)
cd ../backend && uvicorn app.main:app          # http://127.0.0.1:8000
```

Run the samples **top to bottom after "Reset demo data"**: some depend on earlier ones, just as in real life.
Full setup: [docs/SETUP.md](docs/SETUP.md). Deploy steps: [docs/DEPLOY.md](docs/DEPLOY.md); the demo script is in [docs/DEMO.md](docs/DEMO.md).

## How it's built

| Part | Choice | Why |
|---|---|---|
| Reading (main) | Gemini (free tier) asked for JSON matching the Pydantic schema; Claude is a drop-in alternative via `LLM_PROVIDER=claude`. Page images for scans | One schema for every layout; null instead of guessing; one retry on invalid output |
| Reading (fallback) | pdfplumber for text PDFs; denoise + deskew + Tesseract for scans | Runs with no API, and takes over automatically if the AI reader fails or hits its free-tier limit |
| Confidence | Reader's score adjusted by cross-checks: lines → subtotal → total, GSTIN checksum | A confidence that means something, whichever reader produced it |
| Decisions | 12 plain Python rules (`backend/app/rules.py`), each returns status + reason + evidence | Deterministic, unit-tested, explainable |
| Matching | rapidfuzz for vendor names and item descriptions | Vendors and items are never spelled the same twice |
| API | FastAPI; Server-Sent Events stream each stage to the UI | Live run view without WebSockets |
| UI | React + Vite, built inside the Docker image | Landing page, live run view, history dashboard, reviewer approve/reject, rule settings |
| Storage | SQLite (vendors, POs, runs, steps, audit log) | Zero setup for a demo |

Notable decisions:
- **Missing vs unreadable.** A field absent from a digital PDF is missing, so the invoice is rejected and the vendor is asked to resend it. The same field not found on a scan may just be unreadable, so a person checks it.
- **Misread vs mismatched GSTIN.** One that fails its checksum is treated as a reading error. A valid one that differs from the master is possible impersonation, so the invoice is held.
- **Duplicates count only invoices that were accepted or held.** A corrected re-send of a rejected invoice is not a duplicate.
- **One invoice at a time.** Later invoices must see earlier decisions (split POs, duplicates). At scale this becomes a lock per PO.
- **People stay in charge.** Held invoices need a reviewer's note to approve or reject. The rules' original decision is kept, and every step is in the audit trail.

## Assumptions

Fictional buyer Kestrel Components Pvt Ltd (Pune, Maharashtra), about 300 invoices a month. INR and GST: CGST + SGST for
in-state vendors, IGST for out-of-state. 2-way match (invoice vs PO); goods receipts are out of scope. The process
stops at the decision; it never pays. Vendors and POs are seeded from `data/seed/`.

## Tests

```bash
cd backend && pytest -q                       # 8 samples in demo order, review, highlights, foreign invoice, provider fallback (31)
python scripts/extract_all.py                 # extraction accuracy vs data/ground_truth.json
python scripts/generate_test_data.py          # rebuild every sample PDF, seed CSV and expected result
```

Local reader: 70/72 fields (97 %) correct across the samples. Both misses are on the scan, and both are flagged as low confidence.

## Limitations and next steps

- 3-way match with goods receipt notes; partial approval of a line ("approve 40 of 55")
- Email intake (forward-to address) and a vendor portal for missing details
- Postgres, a worker queue and per-PO locks for volume; batch API calls
- Learn tolerances and confidence floors from reviewer overrides
- Multi-currency and non-GST tax regimes (today a non-INR invoice is held for a person)

## Repo

```
backend/app/        main.py (API), pipeline.py (stages), rules.py (decisions), extract/ (Gemini or Claude, plus local readers)
backend/tests/      end-to-end decision tests
frontend/src/       React UI (frontend/dist is the built copy the backend serves)
data/               seed CSVs, 8 sample invoices, expected decisions, extraction ground truth
scripts/            test-data generator, extraction scorer
docs/               DEPLOY.md, DEMO.md
Dockerfile, render.yaml
```
