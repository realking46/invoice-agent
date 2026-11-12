"""PDF helpers: classify text vs scan, render pages, OCR with clean-up and deskew."""
import io

import fitz  # PyMuPDF
import pdfplumber
from PIL import Image, ImageFilter

from .. import config


def pdf_text(path) -> tuple[str, list[int]]:
    """All extractable text, plus character count per page."""
    texts, counts = [], []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            texts.append(t)
            counts.append(len(t.strip()))
    return "\n".join(texts), counts


def classify(path) -> dict:
    text, counts = pdf_text(path)
    scanned = all(c < config.SCAN_TEXT_THRESHOLD for c in counts)
    return {"route": "scan" if scanned else "text", "pages": len(counts), "chars_per_page": counts, "text": text}


def render_pages(path, dpi=200) -> list[Image.Image]:
    out = []
    with fitz.open(path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return out


def png_bytes(img: Image.Image, max_side=1600) -> bytes:
    img = img.copy()
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _skew_angle(binary: Image.Image) -> float:
    """Projection-profile deskew: the angle whose row sums are 'spikiest' aligns the text lines."""
    import numpy as np

    small = binary.copy()
    small.thumbnail((900, 900))
    best, best_score = 0.0, -1.0
    for tenth in range(-40, 41, 2):  # -4.0° .. +4.0° in 0.2° steps
        a = tenth / 10
        rot = np.asarray(small.rotate(a, resample=Image.BILINEAR, fillcolor=255))
        rows = (rot < 128).sum(axis=1).astype(np.int64)
        score = float(((rows[1:] - rows[:-1]) ** 2).sum())
        if score > best_score:
            best, best_score = a, score
    return best


def ocr_page(img: Image.Image) -> tuple[str, float, float]:
    """Returns (text, mean word confidence 0-1, deskew angle)."""
    import pytesseract

    g = img.convert("L").filter(ImageFilter.MedianFilter(5))
    bw = g.point(lambda p: 255 if p > 150 else 0)
    angle = _skew_angle(bw)
    bw = bw.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    text = pytesseract.image_to_string(bw, config="--psm 6")
    data = pytesseract.image_to_data(bw, config="--psm 6", output_type=pytesseract.Output.DICT)
    confs = [float(c) for c in data["conf"] if str(c) not in ("-1", "-1.0")]
    mean = (sum(confs) / len(confs) / 100) if confs else 0.0
    return text, round(mean, 3), angle
