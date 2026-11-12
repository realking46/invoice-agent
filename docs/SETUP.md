# Invoice Agent — Setup Guide (free version)

Everything in this guide costs nothing: Google's free Gemini tier reads the invoices, Render's free plan hosts the
live link, and a free uptime ping keeps it awake. Claude (paid) is an optional swap, covered at the end of Step 2.

## Before you start

About 20 minutes gets the app running on your laptop at http://127.0.0.1:8000, and another 30 minutes puts it on a
free public URL. Everything below assumes you unzipped `zamp-invoice-agent.zip`; commands run from that folder unless
a step says otherwise.

| Tool | Needed for | macOS | Windows | Linux (Ubuntu) |
| --- | --- | --- | --- | --- |
| Python 3.11 or 3.12 | Running the app (3.10+ works) | `brew install python@3.12` | python.org installer; tick "Add python.exe to PATH" | `sudo apt install python3 python3-venv` |
| Tesseract OCR | Local fallback reader for scans | `brew install tesseract` | UB Mannheim installer (github.com/UB-Mannheim/tesseract); add its folder to PATH | `sudo apt install tesseract-ocr` |
| Gemini API key (free) | AI reading of invoices | aistudio.google.com → Get API key | same | same |
| Git + GitHub account (free) | Deploying | `brew install git` | git-scm.com | `sudo apt install git` |
| Render account (free) | Hosting the live link | render.com, sign in with GitHub | same | same |
| cron-job.org account (free) | Keeping the free host awake | cron-job.org | same | same |
| Node.js 18+ | Only if you change the UI | `brew install node` | nodejs.org | nodejs.org or nvm |

Check them with `python --version`, `tesseract --version` and `git --version`. Node is optional: the built UI is
already in `frontend/dist` and the backend serves it.

**Getting the Gemini key:** sign in at aistudio.google.com with a Google account, choose **Get API key → Create API
key**, and copy it. The free tier needs no card. Its limits are per day and change from time to time; the app caches
results and falls back to local OCR if the limit is hit, so a demo never stops.

## Step 1: Unzip and install

Unzip into a folder without spaces in its path (for example `~/projects/zamp-invoice-agent`), then create an
isolated Python environment.

macOS / Linux:

```bash
cd ~/projects/zamp-invoice-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Windows (PowerShell):

```powershell
cd C:\projects\zamp-invoice-agent
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

Your prompt now starts with `(.venv)`. Activate it again in every new terminal before running the app.

## Step 2: Add your free Gemini key

```bash
cp .env.example .env          # Windows: copy .env.example .env
```

Open `.env` and paste your key after `GEMINI_API_KEY=`. Leave the rest as it is. The app reads `.env`
automatically, and `.gitignore` keeps it off GitHub.

| Setting | Default | What it does |
| --- | --- | --- |
| `GEMINI_API_KEY` | empty | Free key from AI Studio. Without any key, the local reader (pdfplumber + Tesseract) is used |
| `GEMINI_MODEL` | `gemini-2.5-flash` | If AI Studio no longer lists this model, put the current free Flash model's name here |
| `LLM_PROVIDER` | `gemini` | `gemini`, `claude`, or `auto` (whichever key is set, Gemini first) |
| `EXTRACTOR` | `auto` | `auto` = AI if a key is set; `llm` = always AI; `local` = never AI |
| `LLM_CACHE` | `1` | Reuses the AI's reading of an identical file: saves free quota, identical demo runs |
| `APP_PASSWORD` | empty | When set, the browser asks for it (any username). Leave empty locally |
| `ANTHROPIC_API_KEY`, `LLM_MODEL` | empty | Optional paid alternative: set the key and `LLM_PROVIDER=claude` |

Price tolerance, confidence floor and duplicate windows are not in `.env`. Change them on the **Rule settings** page
while the app runs.

## Step 3: Start the app

```bash
cd backend
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and check:

- [ ] The top bar says **Reading with Gemini**. "Reading locally (OCR fallback)" means the key wasn't picked up (see Troubleshooting).
- [ ] Press **Reset demo data**, then run **Clean invoice**: nine checks tick through and it ends **Approved** with a green stamp.
- [ ] Run the rest of the samples top to bottom. Expected: Approved with note, Approved, On hold, Rejected, On hold, On hold, Rejected.
- [ ] Open **Read the invoice** on any run: it should say the fields were read by Gemini.
- [ ] **History** lists all 8 runs; **Rule settings** shows tolerance 2 %, cap ₹500.

API docs are at http://127.0.0.1:8000/docs. Stop the server with Ctrl+C.

## Step 4: Verify with tests

The local reader is already verified (25 tests pass, 97 % field accuracy). Gemini has not been run against these
samples yet, so do it once before you deploy. It uses about 8–16 free requests.

```bash
# from the project root, with .venv active
python scripts/extract_all.py                       # local reader: field accuracy vs data/ground_truth.json
cd backend && pytest -q                             # 8 decisions in demo order + review + provider tests
cd ..
EXTRACTOR=llm python scripts/extract_all.py         # Gemini: field accuracy
```

On Windows PowerShell: `$env:EXTRACTOR="llm"`, run the command, then `Remove-Item Env:EXTRACTOR`.

Then run all 8 samples in the UI once more. If a decision differs from the expected list in Step 3, open that run's
**Read the invoice** step: the cause is almost always one field read differently, usually on the scan. Note it and fix
the prompt in `backend/app/extract/llm.py` or the rule in `backend/app/rules.py`. If you see a rate-limit fallback
note, wait a minute (or until the next day) and run again; cached files won't use quota.

## Step 5 (optional): Change the UI

Skip this unless you edit files in `frontend/src`. Keep the backend from Step 3 running in another terminal.

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173
npm run build        # when done: rebuilds frontend/dist, which the backend serves
```

## Step 6: Deploy free

**6a. Push to a private GitHub repo**

```bash
git init
git add .
git commit -m "Invoice agent: Zamp ASA case study PS-1"
git branch -M main
gh repo create invoice-agent --private --source=. --push
```

No GitHub CLI? Create an empty private repo on github.com, then `git remote add origin <url>` and
`git push -u origin main`.

**6b. Render (free plan)**

1. render.com → **New → Blueprint** → connect GitHub → choose the repo. Render reads `render.yaml` (free plan,
   Dockerfile build).
2. Paste `GEMINI_API_KEY` when asked; set `APP_PASSWORD` if you want the link protected.
3. Wait for the first build (several minutes on the free plan), then open the `.onrender.com` URL.

Free-plan limits to know: the service sleeps after 15 minutes without traffic and takes about a minute to wake;
the machine is small, so the scanned invoice takes longer; and the disk resets on restarts and deploys (run history,
cache, settings). None of this matters for the demo if you follow 6c and 6d.

**6c. Keep it awake (free uptime ping)**

1. Sign up at cron-job.org → **Create cronjob**.
2. URL: `https://<your-app>.onrender.com/api/health` (this one path works even with `APP_PASSWORD` set).
3. Schedule: every 10 minutes. Save.

One always-on free service uses about 744 of Render's 750 free hours a month, so keep only this one free service
running in your Render workspace.

**6d. After it's live**

- [ ] `https://<your-url>/api/health` shows `"provider": "gemini"`
- [ ] The site opens in an incognito window and on your phone
- [ ] Warm the cache: Reset demo data, run all 8 samples once, then Reset again (the cache survives a reset, not a restart)
- [ ] Repeat the warm-up after every deploy or restart

## Before every demo

The full talk track is in `docs/DEMO.md`. For the live interview, the most reliable free setup is your laptop
(Step 3) with screen sharing; keep the Render link as the submitted, always-available version.

- [ ] Open the app in a fresh browser window, zoom 110–125 % for screen sharing
- [ ] Top bar says **Reading with Gemini**
- [ ] **Rule settings**: tolerance 2, cap 500, confidence 0.8, demo pacing 450
- [ ] **Reset demo data**, and run all 8 once beforehand so the cache is warm, then Reset again
- [ ] Run order: samples top to bottom, then History (04 needs 03 first; 05 needs 01 first)
- [ ] Notifications off; this guide and the roadmap open on a second screen

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Top bar says "Reading locally" though you set a key | `.env` not in the project root, or a typo in the variable name | Put `.env` next to `README.md`; the line must start `GEMINI_API_KEY=`; restart the server |
| "The AI reader could not be reached" note in Read the invoice | Free-tier rate limit hit, wrong key, network, or the model name is retired | Wait and retry; check the key in AI Studio; set `GEMINI_MODEL` to a model AI Studio lists. The run still finishes with the local reader |
| `TesseractNotFoundError` on the scanned sample | Tesseract not installed or not on PATH | Install it; on Windows add `C:\Program Files\Tesseract-OCR` to PATH and open a new terminal |
| `.venv\Scripts\Activate.ps1 cannot be loaded` (Windows) | PowerShell script policy | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once |
| `Address already in use` | Another server on port 8000 | Stop it, or run `uvicorn app.main:app --port 8001` |
| Blank page at http://127.0.0.1:8000 | `frontend/dist` missing | `cd frontend && npm install && npm run build`, restart the backend |
| Second partial delivery shows Approved, or the re-sent invoice isn't caught | Samples run out of order, or after old runs | **Reset demo data**, then run samples top to bottom |
| Render link takes a minute to load | Free service was asleep | Check the cron-job.org ping is active and hitting `/api/health` |
| History is empty on Render after a while | Free service restarted (fresh disk) | Expected; Reset demo data and re-run the samples |
| `ModuleNotFoundError` | Virtual environment not active | Activate `.venv` (Step 1) and retry |
| Browser asks for a password | `APP_PASSWORD` is set on the server | Any username, that password; clear the variable to remove it |
