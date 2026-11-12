"""Extraction entry point: classify -> read (LLM or local) -> calibrate confidence with consistency checks."""
import re

from .. import config
from ..schemas import KEY_FIELDS, ExtractionResult, InvoiceExtraction
from . import local_parser
from .pdf_utils import classify, ocr_page, render_pages

GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_valid(g: str | None) -> bool:
    if not g or not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]", g):
        return False
    total = 0
    for i, ch in enumerate(g[:14]):
        p = GST_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += p // 36 + p % 36
    return GST_CHARS[(36 - total % 36) % 36] == g[14]


def read_document(path, route: str, text: str, mode: str) -> tuple[InvoiceExtraction, dict, str]:
    """Returns (extraction, meta, text_used)."""
    if mode == "llm":
        from . import llm
        ext, meta = llm.extract(path, route, text)
        return ext, meta, text
    if route == "text":
        return local_parser.parse(text, base_conf=0.95), {}, text
    # scanned: OCR every page; prior confidence = tesseract's own word confidence, capped
    texts, confs, angles = [], [], []
    for img in render_pages(path, dpi=config.OCR_DPI):
        t, c, a = ocr_page(img)
        texts.append(t), confs.append(c), angles.append(a)
    ocr_text = "\n".join(texts)
    prior = round(min(0.85, sum(confs) / len(confs)), 2)
    return local_parser.parse(ocr_text, base_conf=prior), {"ocr_confidence": confs, "deskew_deg": angles}, ocr_text


def calibrate(ext: InvoiceExtraction) -> list[dict]:
    """Cross-check fields against each other. Agreement raises confidence; disagreement lowers it.
    This is what makes a confidence score mean something, whichever extractor produced it."""
    c = ext.confidence
    checks = []

    def adjust(fields, ok, name, detail):
        checks.append({"check": name, "passed": ok, "detail": detail})
        for f in fields:
            if c.get(f, 0) > 0:
                c[f] = round(min(0.99, c[f] + 0.10), 2) if ok else round(min(c[f], 0.55), 2)

    if ext.line_items and ext.subtotal is not None and all(li.amount is not None for li in ext.line_items):
        s = round(sum(li.amount for li in ext.line_items), 2)
        adjust(["subtotal", "line_items"], abs(s - ext.subtotal) <= 1, "line items sum to subtotal",
               f"{s} vs {ext.subtotal}")
    for li in ext.line_items:
        if None not in (li.quantity, li.unit_price, li.amount) and abs(li.quantity * li.unit_price - li.amount) > 1:
            adjust(["line_items"], False, "qty x rate = amount", f"{li.description[:30]}: "
                   f"{li.quantity} x {li.unit_price} != {li.amount}")
    if None not in (ext.subtotal, ext.tax_total, ext.total):
        adjust(["subtotal", "tax_total", "total"], abs(ext.subtotal + ext.tax_total - ext.total) <= 1,
               "subtotal + tax = total", f"{ext.subtotal} + {ext.tax_total} vs {ext.total}")
    if ext.vendor_gstin:
        adjust(["vendor_gstin"], gstin_valid(ext.vendor_gstin), "vendor GSTIN checksum", ext.vendor_gstin)
    return checks


def _file_hash(path) -> str:
    import hashlib
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def extract(path) -> ExtractionResult:
    info = classify(path)
    mode = config.extractor_mode()
    fallback, cached = None, False
    cache_file = None
    if mode == "llm" and config.LLM_CACHE:
        config.CACHE_DIR.mkdir(exist_ok=True)
        cache_file = config.CACHE_DIR / f"{config.provider()}_{config.model_name()}_{_file_hash(path)}.json"
    if cache_file and cache_file.exists():
        ext, meta, text = InvoiceExtraction.model_validate_json(cache_file.read_text()), {"cached": True}, info["text"]
        cached = True
    else:
        try:
            ext, meta, text = read_document(path, info["route"], info["text"], mode)
            if cache_file:
                cache_file.write_text(ext.model_dump_json())
        except Exception as err:  # LLM unreachable, rate-limited, or returned junk twice: keep the process running
            if mode != "llm":
                raise
            fallback = f"{type(err).__name__}: {str(err)[:400]}"
            mode = "local"
            ext, meta, text = read_document(path, info["route"], info["text"], "local")
    for f in KEY_FIELDS + ["line_items"]:
        ext.confidence.setdefault(f, 0.0 if getattr(ext, f, None) in (None, [], "") else 0.5)
    checks = calibrate(ext)
    floor = config.SETTINGS["confidence_floor"]
    absent = [f for f in KEY_FIELDS if getattr(ext, f) in (None, "")]
    present_low = [f for f in KEY_FIELDS if f not in absent and ext.confidence.get(f, 0) < floor]
    res = ExtractionResult(
        data=ext, route=info["route"], mode=mode, fallback_reason=fallback, cached=cached,
        provider=config.provider() if mode == "llm" else None, checks=checks + ([{"meta": meta}] if meta else []),
        # On a readable PDF an absent field is genuinely missing; on a scan it may just be unreadable.
        missing_fields=absent if info["route"] == "text" else [],
        unreadable_fields=absent if info["route"] == "scan" else [],
        low_confidence_fields=present_low, raw_text=text,
    )
    return res