# Demo runbook

For the 5-minute video and the live interview. Rehearse it three times with a timer before recording.

## 30 minutes before

- [ ] Open the live URL in a fresh browser window, zoom to 110–125 % so text reads on a shared screen
- [ ] Top bar says **Reading with Gemini**. If it says local, the key is missing: fix it, or demo in local mode and say so
- [ ] Run all 8 samples once to warm the cache (saves free-tier quota during the demo), then Reset
- [ ] **Rule settings**: price tolerance 2, cap 500, confidence 0.8, demo pacing 450
- [ ] **Reset demo data** on the home page
- [ ] Close other tabs and notifications. Keep this runbook and the roadmap doc open on a second screen

## Run order (live interview)

Samples must run top to bottom after a reset: 04 depends on 03, and 05 depends on 01.

| # | Sample | Expect | What to point at | One line to say |
|---|---|---|---|---|
| 1 | Clean invoice | Approved | Each check ticking live; open **Read the invoice** to show fields + confidence | "The model only reads. Rules decide, and every decision carries its evidence." |
| 2 | Small extra charge | Approved with note | The ₹472 freight difference vs the ₹500 cap | "Close-but-not-exact is normal. Tolerance is a business setting, not code." |
| 3 | Partial delivery | Approved | Nothing unusual: that is the point | "This one sets up the next." |
| 4 | Second partial delivery | On hold | **Match to purchase order** table: 60 billed before + 55 now vs 100 ordered | "Each invoice looks fine alone. The process remembers what was billed before." |
| 5 | Re-sent invoice | Rejected | "INV 42" vs "INV-0042", different file, different date | "Exact-match duplicate checks miss this. We normalise the number." |
| 6 | Scanned, no order number | On hold | Scan route; low-confidence fields; PO-1007 0.89 vs decoy PO-1008 0.46 | "When it has to guess, it says so and asks a person." |
| 7 | New bank account | On hold | Every check green except bank | "A perfect-looking invoice isn't a safe one. Then approve it as a reviewer, with a note." |
| 8 | Incomplete invoice | Rejected | The drafted vendor email | "Missing on a digital PDF means reject and ask; unreadable on a scan means a person checks." |
| 9 | History | — | Summary row, filters, the reviewed invoice, audit trail | "This is what the AP lead sees at the end of the day." |
| 10 | If asked "what if…" | — | Rule settings → tolerance 0.5 → reset → rerun 01 and 02 | 02 flips to On hold with the new limit in its reason |

## 5-minute video (cut-down)

| Time | Do | Say |
|---|---|---|
| 0:00–0:30 | Home page | The problem; what the process does; "LLM reads, rules decide" |
| 0:30–1:45 | Run **Clean invoice** | Walk the trail as it fills; open the extraction evidence |
| 1:45–2:45 | Run **Partial delivery**, then **Second partial delivery** | The cumulative quantity table |
| 2:45–3:45 | Run **New bank account**, then approve it as reviewer | Fraud signal, review note, audit trail |
| 3:45–4:30 | History page | Decided without a person %, filters, reasons |
| 4:30–5:00 | Close | What you'd build next (below) |

## If something goes wrong live

| Problem | Do this |
|---|---|
| Gemini slow, down or rate-limited | Nothing: it falls back to the local reader automatically and the extraction step says so. Name it as a design choice |
| A run shows the wrong decision | Reset demo data, run from sample 1 again (order matters) |
| Page stuck on "working…" | Refresh: the run view reloads the finished result from the server |
| Site won't load (free host asleep or restarted) | Run it locally (`uvicorn app.main:app`) and share your screen |

## Questions to be ready for

- **Why not let the LLM decide?** Auditability and repeatability: finance teams need rules they can read and change. The LLM is used where rules fail: reading messy documents.
- **How do you stop hallucinated numbers?** The schema allows null, every field carries a confidence and a source snippet, and the arithmetic cross-checks (lines → subtotal → total, GSTIN checksum) lower confidence when numbers don't agree. Below 0.8 goes to a person.
- **What does confidence actually mean here?** The reader's prior, adjusted by whether the document agrees with itself. A misread GSTIN on the scan failed its checksum and dropped to 0.55.
- **10,000 invoices a month?** Queue + workers, Postgres, per-vendor PO locking instead of one global lock, batch API, cache by file hash. Cost: built on free tiers; at volume, a paid Flash-class model costs a fraction of a rupee per invoice. Check current pricing before quoting a number.
- **How would you know it works in production?** Auto-decision rate, human override rate per rule, false-approve rate from audits, time to pay.
- **What's next?** 3-way match with goods receipts; email intake; vendor portal for missing fields; learn tolerances from reviewer overrides; ERP connector.
- **What did you cut?** Point to the assumptions log: 2-way match only, INR/GST only, SQLite, one page of a scan read by the local fallback.
- **Hardest part?** Have one honest story ready. Suggested: inferring the PO on the bundled scan without a decoy PO stealing the match.
