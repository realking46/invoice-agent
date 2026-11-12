"""Local (no-API) extractor: pattern parsing over PDF text or OCR text.

It is the fallback when no LLM key is set or the API is down, and it is deliberately conservative:
anything it is unsure about gets low confidence, so the rules send it to a human."""
import re
from typing import Optional

from rapidfuzz import fuzz

from .. import config
from ..schemas import InvoiceExtraction, LineItem, TaxLine

NUM = r"[\d][\d,. ]*\d"


def to_number(s: Optional[str]) -> Optional[float]:
    """Tolerant of OCR damage: '48.000.00' -> 48000.0, '8.640 00' -> 8640.0, '1,61,660.00' -> 161660.0"""
    if not s:
        return None
    s = s.strip().rstrip(".")
    s = re.sub(r"(\d)[ ](\d{2})$", r"\1.\2", s)  # space read instead of decimal point
    s = s.replace(",", "").replace(" ", "")
    if s.count(".") > 1:  # OCR read thousands separators as dots: keep only the last as decimal
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
    try:
        return float(s)
    except ValueError:
        return None


def to_iso(d: Optional[str]) -> Optional[str]:
    if not d:
        return None
    m = re.match(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", d)
    if not m:
        return None
    dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= dd <= 31 and 1 <= mm <= 12):
        return None
    return f"{yy:04d}-{mm:02d}-{dd:02d}"


ITEM_RE = re.compile(
    r"^\W?\d{0,3}\W?\s*(?P<desc>[A-Za-z][^\n]*?)\s+(?P<hsn>\d{4})\s+(?P<qty>[\d,.]+)\s+(?P<uom>[A-Za-z]+)\s+"
    r"(?P<rate>" + NUM + r")\s+(?P<amt>" + NUM + r")$")
STOP_WORDS = ("taxable value", "cgst", "sgst", "igst", "grand total", "amount payable", "bank details")


def _first(pattern, text, flags=re.I):
    m = re.search(pattern, text, flags)
    return (m.group(1).strip(), m.group(0).strip()) if m else (None, None)


def parse(text: str, base_conf: float) -> InvoiceExtraction:
    ext = InvoiceExtraction()
    conf, ev = {}, {}
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    def put(field, value, snippet, c=base_conf):
        if value not in (None, "", []):
            setattr(ext, field, value)
            conf[field] = c
            ev[field] = (snippet or "")[:120]
        else:
            conf[field] = 0.0

    # vendor name: first line, minus the document title
    if lines:
        name = re.sub(r"\bTAX INVOICE\b", "", lines[0], flags=re.I).strip(" -:|")
        put("vendor_name", name or None, lines[0])

    # GSTINs: the one that is not ours is the vendor's
    gstins = [(m.group(1), m.group(0)) for m in re.finditer(r"GSTIN[:\s]*([0-9A-Z]{15})", text)]
    for g, snip in gstins:
        if fuzz.ratio(g, config.BUYER_GSTIN) >= 90:
            ext.buyer_gstin = g
        elif not ext.vendor_gstin:
            put("vendor_gstin", g, snip)
    if not ext.vendor_gstin:
        conf["vendor_gstin"] = 0.0

    # invoice number: rest of the same line only (never borrow the next line)
    m = re.search(r"Invoice\s*No[:.]?[ \t]*([A-Z0-9][A-Z0-9/\- ]{1,30}?)[ \t]*(?:$|Invoice Date)", text, re.I | re.M)
    put("invoice_number", m.group(1).strip() if m else None, m.group(0) if m else None)

    d, snip = _first(r"Invoice\s*Date[:.]?[ \t]*(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})", text)
    put("invoice_date", to_iso(d), snip)

    po, snip = _first(r"\b(PO[-\s]?\d{3,6})\b", text, 0)
    put("po_reference", po.replace(" ", "-") if po else None, snip)

    # line items (with wrapped descriptions)
    items, last = [], None
    for l in lines:
        m = ITEM_RE.match(l)
        if m:
            last = LineItem(description=m["desc"].strip(), hsn=m["hsn"], quantity=to_number(m["qty"]),
                            uom=m["uom"], unit_price=to_number(m["rate"]), amount=to_number(m["amt"]))
            items.append(last)
        elif last and not any(w in l.lower() for w in STOP_WORDS) and len(l) < 60 and not re.search(r"\d{3}", l):
            last.description += " " + l
            last = None  # at most one continuation line
        elif any(w in l.lower() for w in STOP_WORDS):
            last = None
    ext.line_items = items
    conf["line_items"] = base_conf if items else 0.0

    sub, snip = _first(r"Taxable\s*Value[^\d\n]*(" + NUM + ")", text)
    put("subtotal", to_number(sub), snip)

    taxes = []
    for m in re.finditer(r"\b(CGST|SGST|IGST)\s*@\s*([\d.]+)\s*%[^\d\n]*(" + NUM + ")", text, re.I):
        taxes.append(TaxLine(type=m.group(1).upper(), rate=to_number(m.group(2)), amount=to_number(m.group(3)) or 0))
    ext.tax_lines = taxes
    put("tax_total", round(sum(t.amount for t in taxes), 2) if taxes else None,
        "; ".join(f"{t.type} {t.amount}" for t in taxes))

    tot, snip = _first(r"Grand\s*Total[^\d\n]*(" + NUM + ")", text)
    put("total", to_number(tot), snip)

    acct, snip = _first(r"Account\s*No\W*(\d{6,20})", text)
    put("bank_account", acct, snip)
    ifsc, snip = _first(r"IFSC\W*([A-Z]{4}[0O][A-Z0-9]{6})", text)
    put("ifsc", ifsc[:4] + "0" + ifsc[5:] if ifsc else None, snip)

    note = next((l for l in lines if re.search(r"(updated|changed|new)\b.*bank|bank.*(updated|changed)", l, re.I)), None)
    ext.notes = note
    ext.confidence, ext.evidence = conf, ev
    return ext
