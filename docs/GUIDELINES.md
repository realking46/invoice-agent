# Zamp PS-1 — Problem Statement Guidelines

## The brief

PS-1 asks for a process that takes one vendor invoice PDF and returns a clear, reasoned decision, with every step in between visible. It is one of three problem statements in Zamp's AI Solutions Analyst take-home; we chose it on Day 1.

**The situation Zamp describes:** a mid-size company gets hundreds of vendor invoices a month, all as PDFs by email. An AP clerk opens each one, finds the matching purchase order in a spreadsheet, checks the numbers and decides what to do. It is slow and repetitive, and tired people make expensive mistakes.

**What makes it hard, per the brief:**

| Side | Messiness Zamp calls out |
| --- | --- |
| Invoices | Different layouts per vendor; clean digital PDFs and scanned images; line items itemised or bundled; tax embedded or separate; PO reference explicit or implied; sometimes no invoice number, date or clear total |
| Procurement system | Approved vendors, PO amounts, tolerance thresholds, duplicate detection rules |
| Matching | A vendor may split one PO across several invoices; amounts may be close but not exact |
| Output | The process must make a decision and be able to explain it |

**What is left to us:** what to extract, how to validate, which rules matter, and what the output looks like. Zamp says there is no right answer and to treat ambiguity as part of the exercise: make an assumption, note it, and be ready to defend it.

## Deliverables and schedule

Two things go to the hiring coordinator on Day 7: a link to the live, runnable process and a link to a demo video of at most 5 minutes. If the build moves forward, it is run live in a follow-up interview.

| When | Zamp's instruction | Our status |
| --- | --- | --- |
| Day 1 (Thu 12 Nov) | Pick a problem; email the coordinator with subject "ASA Case Study — [Your Name] — PS-1" | PS-1 chosen; email drafted |
| Days 2–6 | Build a working process that handles real inputs end to end; test the happy path and your edge cases | Built and tested locally: 25 automated tests pass |
| Day 7 (Wed 18 Nov) | Send the live link and the video link | To do: deploy, record, send |
| After submission | Live call: run the happy path and your edge cases, explain decisions; no slides | Runbook ready (`docs/DEMO.md`) |

**Deliverable 1: a working automated process.** It must actually execute, not a mockup or a dashboard that simulates one. It takes a real input, runs the logic, produces a real output. Any stack is allowed. The UI is graded: Zamp expects an intuitive interface with a **live run view** showing each stage as it executes, and a **dashboard** showing history, status and outputs across runs.

**Deliverable 2: a 5-minute demo video** (Loom or any screen recording). Show the happy path running live, then at least one edge case. Narrate what the process does at each step, the decisions it makes, and anything interesting about how it was built. No editing or slides needed.

## What Zamp evaluates

Zamp's core question: given a real operational problem, a week and any AI tools, can you build a process that actually runs, handles real inputs, and deals with edge cases gracefully? They grade three things: whether it works, the judgment behind the design, and how clearly it is explained to a non-technical buyer.

| Zamp's bar for a strong submission | How the build meets it |
| --- | --- |
| A process that actually runs: real input, real logic, clear output | Upload any PDF or pick a sample; 9 stages run; a decision with reason, evidence and next step is stored |
| An intuitive UI and a dashboard to point to | Live run view with an audit trail and an approval stamp; History dashboard with totals, filters and search |
| Edge cases handled deliberately, not ignored | 4 designed edge cases, each with its own rule and plain-English reason (next sections) |
| A demo video that shows it running and explains the thinking | 5-minute plan in `docs/DEMO.md`: happy path, split PO, bank change with reviewer approval, dashboard |
| A live demo where you talk fluently about every decision | Runbook with run order, one line per case, recovery plans and likely questions |
| Clear to a non-technical buyer | Reasons read like an AP lead wrote them, e.g. "60 already billed; this invoice bills 55 (15 over). Approve 40, query 15." |

**The design principle to repeat:** the AI model only reads the document; every decision comes from explicit rules the AP team can read and change. That answers "judgment behind design choices" in one sentence.

## PS-1 requirements mapped to the build

Every difficulty the brief names has a specific answer in the build. Use this table when an interviewer asks "what about X?"

| What the brief says | Where it is handled | How |
| --- | --- | --- |
| Invoices arrive as PDFs | Receive stage | Upload or pick a sample; file fingerprinted (an identical re-upload is caught) |
| Different vendors format them differently | Read stage | AI reader (Gemini, free tier) fills one fixed schema whatever the layout; local parser as fallback |
| Some are clean PDFs, some are scanned images | Check type stage | Text layer present → text route; none → page images to the AI, or denoise + deskew + OCR locally |
| Line items itemised or bundled | PO match stage | Line-by-line match when itemised; bundled lots compared at total level (sample 06) |
| Tax embedded or separated | Validate stage (R4) | CGST + SGST or IGST read; slab must be 5/12/18/28 %; CGST must equal SGST; state checked |
| PO reference explicit or implied | PO match (R9) | Cited PO looked up; if none, inferred from vendor + amount + items and sent to a person to confirm |
| Missing invoice number, date or total | Validate (R1) | Missing on a digital PDF → Reject with a drafted vendor email; unreadable on a scan → Hold |
| Approved vendors | Vendor stage (R5) | GSTIN exact match, else fuzzy name match; blocked or unknown vendors rejected |
| PO amounts and tolerance thresholds | PO match (R10, R12) | ±2 % or ₹500, whichever is lower; editable on the Rule settings page |
| Duplicate detection rules | Duplicate stage (R7, R8) | Normalised invoice number ("INV 42" = "INV-0042"); same amount ±1 % within 7 days → Hold |
| A vendor splits one PO across invoices | PO match (R11) | Tracks quantity already billed on each PO line across earlier accepted invoices |
| Amounts close but not exact | PO match (R12) | Within tolerance → Approve with note; beyond → Hold, naming the line and the gap |
| Must make a decision and explain it | Decide + Route stages | Most severe outcome wins; one-sentence reason, per-rule evidence, owner and next step, audit trail |
| Everything in between visible | Live run view | Each stage streams as it runs; click any stage for its evidence |

## Edge cases

Zamp's rules: design and build 2–4 edge cases of your own; they must be realistic scenarios where the process behaves differently from the happy path; no trivial ones, because the choice shows how well you understand the problem. We built four, plus a backup.

| Edge case | Sample | What happens | Decision | Why it isn't trivial |
| --- | --- | --- | --- | --- |
| EC1 Split PO that over-bills | 03 then 04 | 60 of 100 boxes approved; next invoice bills 55 more | Hold: "approve 40, query 15" | Each invoice looks fine alone; needs memory across runs |
| EC2 Disguised duplicate | 01 then 05 | Same invoice re-sent as "INV 42", redated, new file | Reject | Exact-match duplicate checks miss it; needs normalisation |
| EC3 Scanned, no PO, bundled items | 06 | Image-only scan; PO-1007 inferred (0.89) over a decoy PO-1008 (0.46) | Hold: confirm PO | The process has to know when not to trust itself |
| EC4 Changed bank details | 07 | Every check passes except the bank account | Hold: fraud risk | A perfect-looking invoice is not a safe one |
| Backup: incomplete invoice | 08 | No invoice number, no grand total | Reject + vendor email | Missing (digital PDF) vs unreadable (scan) are treated differently |

The happy path is samples 01 (exact match, Approve) and 02 (freight line within tolerance, Approve with note). Run order matters: reset, then 01 → 08.

## Zamp's guidance and rules

Zamp gave five pieces of advice and a short FAQ. Each one is followed; the right column is what to say if asked.

| Zamp says | What we did |
| --- | --- |
| Map the process on paper before building | Process map and rule table written on Day 1 (roadmap doc) before any code |
| Get the happy path working first, then add edge cases one at a time | Days 2–3: extraction and happy path; edge cases added and tested one by one |
| Use AI tools, deliberately, and be able to explain why each is there | AI reads documents (where templates fail); rules decide (where finance needs auditability); AI also used to build faster |
| Prepare and rehearse demo runs | Fixed sample set, reset button, run order, runbook, automated test of all 8 decisions |
| Submit something that runs, even if imperfect | Runs end to end today; limitations listed in the README |
| Ambiguity: make an assumption, note it, move on | Assumptions table in the roadmap and README (INR/GST, 2 % or ₹500, 2-way match, never pays) |
| Any tools allowed, but **not Zamp or Pace** | Python, FastAPI, React, Gemini (free tier), Tesseract; nothing from Zamp or Pace |
| Create your own test data; realistic enough that the logic is meaningful | 8 generated invoice PDFs (3 layouts, one scanned), 6 vendors, 8 POs, ground-truth file |
| A UI that shows run status and outputs | Live run view + History dashboard + Rule settings |
| Process must run live in the interview | Runs on a free public URL and on the laptop; AI failure falls back to local reading automatically |
| Need more time? Email the coordinator before the deadline; don't go silent | Not needed so far; if anything slips, email before Day 7 |
| No finance background? Build for the person behind the workflow | Reasons, owners and next steps written for the AP clerk, treasury and procurement |

## Submission and interview checklist

Tick these off in order; everything before "Send" must be done by Day 7.

**Before Day 7**

- [ ] Day 1 email sent: "ASA Case Study — Nishant Singh — PS-1"
- [ ] Free Gemini key added; all 8 samples give the expected decisions with Gemini (Setup Guide, Step 4)
- [ ] Deployed on Render free plan; keep-alive ping every 10 minutes; `/api/health` shows `"provider": "gemini"`
- [ ] Live link opens in incognito and on a phone; cache warmed, then demo data reset
- [ ] Video recorded: happy path + at least one edge case, narrated, under 5:00
- [ ] README reviewed: assumptions, limitations, next steps

**Send (Day 7)**

- [ ] Email the coordinator: live link (+ password if set), video link, optional GitHub link
- [ ] If anything slipped, say so in the email: what works, what's left

**Before the interview**

- [ ] App running on the laptop as backup; Rule settings at defaults; demo data reset
- [ ] Runbook open: run order 01 → 08, then History; reviewer approval on 07
- [ ] Ready to explain: why the AI only reads; missing vs unreadable; how confidence is checked; what you'd build next
