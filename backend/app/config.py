"""Central settings. Every threshold the rules use lives here so it can be changed live in the demo."""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent

try:  # read settings from a .env file in the repo root, if present (real environment variables still win)
    from dotenv import load_dotenv
    load_dotenv(REPO_DIR / ".env", override=False)
except ImportError:
    pass
SEED_DIR = REPO_DIR / "data" / "seed"
SAMPLES_DIR = REPO_DIR / "data" / "invoices"
UPLOAD_DIR = BACKEND_DIR / "uploads"
DB_PATH = Path(os.getenv("DB_PATH", BACKEND_DIR / "invoice_agent.db"))
UPLOAD_DIR.mkdir(exist_ok=True)

# Buyer (our company) — used to tell the vendor's GSTIN apart from ours on the invoice
BUYER_NAME = "Kestrel Components Pvt Ltd"
BUYER_GSTIN = "27AAFCK4821N1Z7"

# Extraction
# EXTRACTOR: "auto" (LLM if a key is set, else local), "llm", or "local"
EXTRACTOR = os.getenv("EXTRACTOR", "auto")
# LLM_PROVIDER: "gemini" (free tier, default), "claude", or "auto" (whichever key is set; Gemini first)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")  # tried if the main model is busy
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5")   # Claude model, used when the provider is claude
LLM_CACHE = os.getenv("LLM_CACHE", "1") == "1"   # reuse the LLM's reading of an identical file
CACHE_DIR = BACKEND_DIR / "cache"
SCAN_TEXT_THRESHOLD = 50  # fewer extractable characters than this on a page => treat as scanned
OCR_DPI = 300


def provider() -> str | None:
    """Which LLM reads invoices, or None if no key is configured."""
    has_gemini, has_claude = bool(os.getenv("GEMINI_API_KEY")), bool(os.getenv("ANTHROPIC_API_KEY"))
    if LLM_PROVIDER == "gemini":
        return "gemini" if has_gemini else None
    if LLM_PROVIDER == "claude":
        return "claude" if has_claude else None
    return "gemini" if has_gemini else "claude" if has_claude else None


def model_name() -> str | None:
    p = provider()
    return GEMINI_MODEL if p == "gemini" else LLM_MODEL if p == "claude" else None


def llm_available() -> bool:
    return provider() is not None


def extractor_mode() -> str:
    if EXTRACTOR in ("llm", "local"):
        return EXTRACTOR
    return "llm" if llm_available() else "local"


# Decision thresholds (used from Day 3; editable via /api/config)
SETTINGS = {
    "price_tolerance_pct": 2.0,      # A5: ±2 % ...
    "price_tolerance_abs": 500.0,    # ... or ₹500, whichever is lower
    "confidence_floor": 0.80,        # A9: below this on a key field => Hold
    "duplicate_amount_pct": 1.0,     # A8: probable duplicate if amount within 1 % ...
    "duplicate_window_days": 7,      # ... and date within 7 days
    "demo_pacing_ms": 450,           # minimum visible time per stage in the live view (0 = run at full speed)
}
