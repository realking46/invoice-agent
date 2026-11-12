# Deploy guide (free)

The full walkthrough is Step 6 of [SETUP.md](SETUP.md). This page is the short version plus what lives where.

1. Run it locally with your free Gemini key first (SETUP.md Steps 1–4).
2. Push to a private GitHub repo.
3. render.com → **New → Blueprint** → pick the repo. `render.yaml` selects the **free** plan and the Dockerfile.
   Paste `GEMINI_API_KEY` (and optionally `APP_PASSWORD`).
4. cron-job.org → new cron job → `https://<your-app>.onrender.com/api/health` every 10 minutes, so the free service
   doesn't sleep.
5. Open the URL, check `/api/health` shows `"provider": "gemini"`, warm the cache by running all 8 samples, then
   Reset demo data.

**Railway or other hosts:** any host that builds a Dockerfile works. Set `GEMINI_API_KEY`; the host provides `PORT`.

## What lives where

| Thing | Where | Survives a restart or redeploy? |
|---|---|---|
| Vendors, POs | `data/seed/*.csv` → SQLite on startup | Yes (re-seeded) |
| Runs, decisions, audit trail | SQLite in the container | No (fine for a demo; Postgres for real use) |
| AI reading cache | `backend/cache/` | No |
| Settings changed in the UI | Memory | No (defaults in `backend/app/config.py`) |
