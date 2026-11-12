"""
Generate Day-1 test data for the Zamp ASA case study (PS-1, invoice processing).

Writes:
  data/seed/vendors.csv, purchase_orders.csv, po_lines.csv   -> procurement "system"
  data/invoices/01..08_*.pdf                                  -> test inputs
  data/expected_decisions.csv                                 -> what the pipeline must output

Run:  python scripts/generate_test_data.py
Everything here is fictional. GSTINs are format- and checksum-valid but made up.
"""
import csv
import io
import random
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed"
INV = ROOT / "data" / "invoices"
SEED.mkdir(parents=True, exist_ok=True)
INV.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- helpers
GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin(state: str, pan: str, entity: str = "1") -> str:
    """Build a GSTIN with a valid checksum character (standard mod-36 algorithm)."""
    base = f"{state}{pan}{entity}Z"
    total = 0
    for i, ch in enumerate(base):
        prod = GST_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += prod // 36 + prod % 36
    return base + GST_CHARS[(36 - total % 36) % 36]


def inr(x: float) -> str:
    """Indian digit grouping: 161660.0 -> 1,61,660.00"""
    neg = x < 0
    whole, frac = f"{abs(x):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return ("-" if neg else "") + whole + "." + frac


# ---------------------------------------------------------------- buyer + vendors
BUYER = {
    "name": "Kestrel Components Pvt Ltd",
    "addr": "Plot 14, MIDC Phase II, Chakan, Pune, Maharashtra 410501",
    "gstin": gstin("27", "AAFCK4821N"),
}

VENDORS = [
    # id, legal name, aliases, state code, PAN, address, bank account, IFSC, status, terms(days)
    ("V001", "Shreeji Steel Traders", "Shreeji Steel|Shreeji Steels", "27", "AAKFS1234L",
     "Gala 7, Bhosari Industrial Area, Pune, Maharashtra 411026", "50100234114521", "HDFC0001234", "approved", 30),
    ("V002", "Vega Fasteners Pvt Ltd", "Vega Fasteners|Vega Fastners", "29", "AACCV5678M",
     "No. 42, Peenya 2nd Stage, Bengaluru, Karnataka 560058", "002105017730", "ICIC0002211", "approved", 45),
    ("V003", "Orbit Packaging Solutions", "Orbit Packaging|Orbit Pack", "27", "AAGFO9012P",
     "Survey 88, Talawade MIDC, Pune, Maharashtra 411062", "38291003318", "SBIN0004567", "approved", 30),
    ("V004", "Nilgiri Industrial Supplies", "Nilgiri Industrial|Nilgiri Supplies", "33", "AAECN3456Q",
     "14 Ambattur Industrial Estate, Chennai, Tamil Nadu 600058", "917020046604", "UTIB0000789", "approved", 30),
    ("V005", "Bharat Electricals & Controls", "Bharat Electricals|Bharat Electrical and Controls", "07", "AABCB7890R",
     "B-27 Okhla Industrial Area Phase I, New Delhi 110020", "4611002295", "KKBK0000456", "approved", 45),
    ("V006", "Apex Traders", "Apex Trading Co", "27", "AAHFA2468S",
     "Shop 3, Market Yard, Pune, Maharashtra 411037", "60112009981", "BARB0PUNEXX", "blocked", 30),
]
V = {}
for vid, name, aliases, st, pan, addr, acct, ifsc, status, terms in VENDORS:
    V[vid] = dict(vendor_id=vid, legal_name=name, aliases=aliases, state_code=st, gstin=gstin(st, pan),
                  pan=pan, address=addr, bank_account=acct, ifsc=ifsc, status=status, payment_terms_days=terms)

# ---------------------------------------------------------------- purchase orders
# po_number: (vendor, po_date, [(item_code, description, qty, unit, unit_price, tax_rate)])
POS = {
    "PO-1001": ("V001", "2026-10-20", [
        ("MS-SHT-2MM", "Mild steel sheet 2 mm (1250x2500)", 50, "Nos", 2400, 18),
        ("MS-ROD-12", "MS round bar 12 mm", 200, "Kg", 85, 18)]),
    "PO-1002": ("V003", "2026-10-22", [
        ("CB-BOX-L5", "Corrugated box large, 5-ply", 1000, "Nos", 42, 18),
        ("STR-FILM-23", "Stretch film roll 23 micron", 60, "Rolls", 310, 18)]),
    "PO-1003": ("V003", "2026-10-25", [
        ("BW-ROLL-1M", "Bubble wrap roll 1 m x 100 m", 30, "Rolls", 1450, 18)]),
    "PO-1004": ("V002", "2026-10-18", [
        ("HB-M10-SS", "Hex bolt M10x40 SS304 (box of 100)", 100, "Box", 1150, 18)]),
    "PO-1005": ("V005", "2026-10-21", [
        ("MCB-32A-4P", "MCB 32A 4-pole C-curve", 40, "Nos", 1850, 18),
        ("CTR-25A", "Power contactor 25A AC3", 20, "Nos", 2100, 18)]),
    "PO-1006": ("V001", "2026-10-28", [
        ("AL-SHT-1.5", "Aluminium sheet 1.5 mm (1220x2440)", 30, "Nos", 3200, 18)]),
    "PO-1007": ("V004", "2026-10-24", [
        ("SG-NITRILE", "Safety gloves nitrile (pair)", 400, "Pairs", 45, 18),
        ("SG-GOGGLE-AF", "Safety goggles anti-fog", 150, "Nos", 120, 18),
        ("EP-BOX-200", "Ear plugs foam (box of 200)", 40, "Box", 300, 18)]),
    "PO-1008": ("V004", "2026-10-26", [
        ("CD-4IN", "Cutting disc 4 inch", 500, "Nos", 38, 18),
        ("GW-7IN", "Grinding wheel 7 inch", 60, "Nos", 450, 18)]),
}

with open(SEED / "vendors.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(V["V001"].keys()))
    w.writeheader()
    w.writerows(V.values())

with open(SEED / "purchase_orders.csv", "w", newline="") as f, open(SEED / "po_lines.csv", "w", newline="") as g:
    wp = csv.writer(f)
    wl = csv.writer(g)
    wp.writerow(["po_number", "vendor_id", "po_date", "currency", "subtotal", "tax", "total_amount", "status"])
    wl.writerow(["po_number", "line_no", "item_code", "description", "qty", "uom", "unit_price", "tax_rate"])
    for po, (vid, d, lines) in POS.items():
        sub = sum(q * p for _, _, q, _, p, _ in lines)
        tax = sum(q * p * t / 100 for _, _, q, _, p, t in lines)
        wp.writerow([po, vid, d, "INR", f"{sub:.2f}", f"{tax:.2f}", f"{sub + tax:.2f}", "open"])
        for i, (code, desc, q, uom, p, t) in enumerate(lines, 1):
            wl.writerow([po, i, code, desc, q, uom, f"{p:.2f}", t])

# ---------------------------------------------------------------- invoice rendering
BASE = ParagraphStyle("b", fontName="Helvetica", fontSize=9, leading=12)
SMALL = ParagraphStyle("s", parent=BASE, fontSize=8, leading=10, textColor=colors.HexColor("#444444"))
H1 = ParagraphStyle("h1", parent=BASE, fontName="Helvetica-Bold", fontSize=15, leading=19)
H2 = ParagraphStyle("h2", parent=BASE, fontName="Helvetica-Bold", fontSize=11, leading=14)
RIGHT = ParagraphStyle("r", parent=BASE, alignment=2)
TRUTH = {}  # file -> what a perfect extractor should return (data/ground_truth.json)


def render_invoice(path, *, vendor, inv_no, inv_date, po_ref, lines, style="A", extra_lines=None,
                   bank=None, show_total=True, bank_note=None, bundled_desc=None):
    """lines: [(desc, hsn, qty, uom, rate, tax_rate)]; extra_lines: same shape (e.g. freight)."""
    v = V[vendor]
    intra = v["state_code"] == BUYER["gstin"][:2]
    all_lines = list(lines) + list(extra_lines or [])
    if bundled_desc:  # collapse into one lot line (EC3)
        amt = sum(q * r for _, _, q, _, r, _ in lines)
        all_lines = [(bundled_desc, "6116", 1, "Lot", amt, lines[0][5])]
    sub = sum(q * r for _, _, q, _, r, _ in all_lines)
    tax = round(sum(q * r * t / 100 for _, _, q, _, r, t in all_lines), 2)
    total = sub + tax
    acct, ifsc = bank or (v["bank_account"], v["ifsc"])

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Invoice {inv_no or ''}", author=v["legal_name"])
    s = []
    accent = {"A": "#1F3A5F", "B": "#333333", "C": "#2E5E3A"}[style]

    # header
    vendor_block = Paragraph(f"<b>{v['legal_name']}</b><br/>{v['address']}<br/>GSTIN: {v['gstin']}", BASE)
    title = Paragraph(f"<font color='{accent}'>TAX INVOICE</font>", H1)
    if style == "B":  # vendor left-aligned, title below
        s += [vendor_block, Spacer(1, 6), title, Spacer(1, 6)]
    else:
        t = Table([[vendor_block, title]], colWidths=[110 * mm, 68 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
        s += [t, Spacer(1, 8)]

    meta = [["Invoice No:", inv_no or ""], ["Invoice Date:", inv_date]]
    if po_ref:
        meta.append(["PO Reference:" if style != "C" else "Your Order No:", po_ref])
    meta.append(["Payment Terms:", f"{v['payment_terms_days']} days"])
    buyer = Paragraph(f"<b>Bill To</b><br/>{BUYER['name']}<br/>{BUYER['addr']}<br/>GSTIN: {BUYER['gstin']}", BASE)
    mt = Table(meta, colWidths=[28 * mm, 40 * mm])
    mt.setStyle(TableStyle([("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 2)]))
    hdr = Table([[buyer, mt]], colWidths=[110 * mm, 68 * mm])
    hdr.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    s += [hdr, Spacer(1, 10)]

    # line items
    rows = [["#", "Description", "HSN", "Qty", "UoM", "Rate (INR)", "Amount (INR)"]]
    for i, (d, hsn, q, uom, r, _) in enumerate(all_lines, 1):
        rows.append([str(i), Paragraph(d, BASE), hsn, f"{q:g}", uom, inr(r), inr(q * r)])
    lt = Table(rows, colWidths=[8 * mm, 72 * mm, 16 * mm, 14 * mm, 14 * mm, 25 * mm, 29 * mm], repeatRows=1)
    ts = [("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
          ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black), ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.grey)]
    if style == "A":
        ts += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(accent)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5F9")])]
    elif style == "C":
        ts += [("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E3EFE5"))]
    lt.setStyle(TableStyle(ts))
    s += [lt, Spacer(1, 8)]

    # totals: CGST+SGST for intra-state, IGST for inter-state
    rate = all_lines[0][5]
    tot = [["Taxable Value", inr(sub)]]
    if intra:
        tot += [[f"CGST @ {rate / 2:g}%", inr(tax / 2)], [f"SGST @ {rate / 2:g}%", inr(tax / 2)]]
    else:
        tot += [[f"IGST @ {rate:g}%", inr(tax)]]
    if show_total:
        tot += [["Grand Total (INR)", inr(total)]]
    else:
        tot += [["Amount Payable", "As per statement"]]
    tt = Table(tot, colWidths=[45 * mm, 35 * mm], hAlign="RIGHT")
    tt.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                            ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black)]))
    s += [tt, Spacer(1, 14)]

    # bank + footer
    s += [Paragraph("<b>Bank Details for Payment</b>", H2),
          Paragraph(f"Account Name: {v['legal_name']}<br/>Account No: {acct}<br/>IFSC: {ifsc}", BASE)]
    if bank_note:
        s += [Spacer(1, 4), Paragraph(f"<b>{bank_note}</b>", BASE)]
    s += [Spacer(1, 18),
          Paragraph("Certified that the particulars given above are true and correct. "
                    "Goods once sold will not be taken back. Subject to local jurisdiction.", SMALL),
          Spacer(1, 18), Paragraph(f"For {v['legal_name']}<br/><br/>Authorised Signatory", RIGHT)]
    doc.build(s)
    d, m, y = inv_date.split("-")
    TRUTH[path.name.replace("_06_clean_source", "06_scanned_no_po")] = {
        "vendor_gstin": v["gstin"], "invoice_number": inv_no, "invoice_date": f"{y}-{m}-{d}",
        "po_reference": po_ref, "subtotal": round(sub, 2), "tax_total": round(tax, 2),
        "total": round(total, 2) if show_total else None, "bank_account": acct, "ifsc": ifsc,
        "line_count": len(all_lines)}
    return round(sub, 2), round(tax, 2), round(total, 2)


def to_scanned(src: Path, dst: Path, seed: int = 7):
    """Rasterise a PDF and rebuild it as an image-only 'scan': grey, skewed, noisy, slightly blurred."""
    rnd = random.Random(seed)
    pages = []
    with fitz.open(src) as d:
        for page in d:
            pix = page.get_pixmap(dpi=150)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
            img = img.rotate(1.3, resample=Image.BICUBIC, expand=False, fillcolor=245)
            img = img.filter(ImageFilter.GaussianBlur(0.6))
            px = img.load()
            w, h = img.size
            for _ in range(w * h // 60):  # speckle noise
                x, y = rnd.randrange(w), rnd.randrange(h)
                px[x, y] = rnd.choice([90, 140, 200])
            img = img.point(lambda p: min(255, int(p * 0.93 + 14)))  # photocopier grey
            pages.append(img.convert("RGB"))
    pages[0].save(dst, "PDF", resolution=150, save_all=True, append_images=pages[1:])


HSN = {"MS": "7208", "AL": "7606", "CB": "4819", "STR": "3920", "BW": "3921", "HB": "7318", "MCB": "8536",
       "CTR": "8536", "SG": "4015", "EP": "3926", "CD": "6804", "GW": "6804"}


def po_lines_for(po, qty_override=None):
    vid, _, lines = POS[po]
    out = []
    for i, (code, desc, q, uom, p, t) in enumerate(lines):
        qty = qty_override[i] if qty_override else q
        out.append((desc, HSN[code.split("-")[0]], qty, uom, p, t))
    return out


# ---------------------------------------------------------------- the 8 test invoices
expected = []

# 01 Happy path: clean, explicit PO, exact match
render_invoice(INV / "01_happy_clean.pdf", vendor="V001", inv_no="INV-0042", inv_date="03-11-2026",
               po_ref="PO-1001", lines=po_lines_for("PO-1001"), style="A")
expected.append(("01_happy_clean.pdf", "Shreeji Steel Traders", "INV-0042", "PO-1001", "Approve",
                 "Clean text PDF; lines, prices and total match PO-1001 exactly"))

# 02 Happy path with tolerance: freight line not on PO, +472 incl. tax (0.66%) -> within 2% and under 500 cap
render_invoice(INV / "02_happy_tolerance.pdf", vendor="V003", inv_no="OPS/2026/118", inv_date="05-11-2026",
               po_ref="PO-1002", lines=po_lines_for("PO-1002"),
               extra_lines=[("Freight & handling charges", "9965", 1, "Lot", 400, 18)], style="C")
expected.append(("02_happy_tolerance.pdf", "Orbit Packaging Solutions", "OPS/2026/118", "PO-1002",
                 "Approve with note", "Extra freight line of 472 incl. tax (+0.66%), within tolerance"))

# 03 Split PO part 1: 60 of 100 boxes
render_invoice(INV / "03_split_po_part1.pdf", vendor="V002", inv_no="VF-2611-0087", inv_date="06-11-2026",
               po_ref="PO-1004", lines=po_lines_for("PO-1004", [60]), style="B")
expected.append(("03_split_po_part1.pdf", "Vega Fasteners Pvt Ltd", "VF-2611-0087", "PO-1004", "Approve",
                 "Partial delivery: 60 of 100 boxes; within PO"))

# 04 Split PO part 2: 55 more boxes -> cumulative 115 of 100 (EC1)
render_invoice(INV / "04_split_po_part2_over.pdf", vendor="V002", inv_no="VF-2611-0103", inv_date="10-11-2026",
               po_ref="PO-1004", lines=po_lines_for("PO-1004", [55]), style="B")
expected.append(("04_split_po_part2_over.pdf", "Vega Fasteners Pvt Ltd", "VF-2611-0103", "PO-1004",
                 "Hold for review", "EC1: cumulative 115 of 100 boxes billed; 15 over PO (run after 03)"))

# 05 Disguised duplicate of 01: 'INV 42', date +2 days (EC2)
render_invoice(INV / "05_duplicate_renumbered.pdf", vendor="V001", inv_no="INV 42", inv_date="05-11-2026",
               po_ref="PO-1001", lines=po_lines_for("PO-1001"), style="A")
expected.append(("05_duplicate_renumbered.pdf", "Shreeji Steel Traders", "INV 42", "PO-1001", "Reject",
                 "EC2: normalises to same number as INV-0042 (run after 01)"))

# 06 Scanned, no PO reference, bundled line (EC3) -> must infer PO-1007 (not PO-1008)
tmp = INV / "_06_clean_source.pdf"
render_invoice(tmp, vendor="V004", inv_no="NIS/1123", inv_date="07-11-2026", po_ref=None,
               lines=po_lines_for("PO-1007"), style="C",
               bundled_desc="Industrial safety consumables (gloves, goggles, ear plugs) as per your order")
to_scanned(tmp, INV / "06_scanned_no_po.pdf")
tmp.unlink()
expected.append(("06_scanned_no_po.pdf", "Nilgiri Industrial Supplies", "NIS/1123", "(inferred) PO-1007",
                 "Hold for review", "EC3: image-only scan, no PO, bundled lot; best match PO-1007 by amount + items"))

# 07 Bank details changed (EC4)
render_invoice(INV / "07_bank_changed.pdf", vendor="V005", inv_no="BEC/26-27/0311", inv_date="08-11-2026",
               po_ref="PO-1005", lines=po_lines_for("PO-1005"), style="A",
               bank=("50200017738890", "YESB0000312"),
               bank_note="Please note: we have updated our bank account. Kindly remit to the account above.")
expected.append(("07_bank_changed.pdf", "Bharat Electricals & Controls", "BEC/26-27/0311", "PO-1005",
                 "Hold for review", "EC4: bank account differs from vendor master (fraud risk)"))

# 08 Missing invoice number and grand total (backup case)
render_invoice(INV / "08_missing_fields.pdf", vendor="V003", inv_no=None, inv_date="09-11-2026",
               po_ref="PO-1003", lines=po_lines_for("PO-1003"), style="B", show_total=False)
expected.append(("08_missing_fields.pdf", "Orbit Packaging Solutions", "(missing)", "PO-1003", "Reject",
                 "No invoice number, no grand total; auto-draft vendor request"))

with open(ROOT / "data" / "expected_decisions.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["file", "vendor", "invoice_no", "po", "expected_decision", "why"])
    w.writerows(expected)

import json  # noqa: E402

(ROOT / "data" / "ground_truth.json").write_text(json.dumps(TRUTH, indent=2))

print("vendors:", len(V), "| POs:", len(POS), "| invoices:", len(expected))
for vid, v in V.items():
    print(vid, v["gstin"], v["legal_name"])
print("buyer", BUYER["gstin"])
