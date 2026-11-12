"""LLM extractors. Text PDFs send the extracted text; scans send page images.

Two providers fill the same InvoiceExtraction schema:
  - Gemini (Google AI Studio free tier, default): asked for JSON matching the schema
  - Claude (Anthropic API, paid): forced through a tool whose input schema IS the model
Output is validated by Pydantic. On a schema failure we retry once with the validation error;
a second failure raises, and the caller falls back to the local reader."""
import base64
import json
import re
import time

from pydantic import ValidationError

from .. import config
from ..schemas import InvoiceExtraction
from .pdf_utils import png_bytes, render_pages

SYSTEM = (
    "You extract data from Indian GST vendor invoices for an accounts-payable team. "
    "Copy values exactly as printed. Never guess: if a field is absent or unreadable, return null and give it "
    "confidence 0. Dates as YYYY-MM-DD (invoices use DD-MM-YYYY). Amounts as plain numbers without commas. "
    f"The buyer is {config.BUYER_NAME} (GSTIN {config.BUYER_GSTIN}); vendor_gstin is the OTHER GSTIN. "
    "po_reference is only a purchase-order number explicitly printed on the invoice. "
    "In confidence, give a 0-1 score for each of: vendor_name, vendor_gstin, invoice_number, invoice_date, "
    "po_reference, subtotal, tax_total, total, bank_account, ifsc, line_items. "
    "In evidence, give the short text snippet each of those was read from. "
    "Put any notice about changed bank details or other unusual remarks in notes."
)

# A compact description of the target JSON, for providers that take free-form JSON instead of a tool schema.
JSON_SHAPE = """Return ONLY one JSON object, no prose, with exactly these keys:
{"vendor_name": str|null, "vendor_gstin": str|null, "buyer_gstin": str|null, "invoice_number": str|null,
 "invoice_date": "YYYY-MM-DD"|null, "po_reference": str|null, "currency": "INR",
 "line_items": [{"description": str, "hsn": str|null, "quantity": number|null, "uom": str|null,
                 "unit_price": number|null, "amount": number|null}],
 "subtotal": number|null, "tax_lines": [{"type": "CGST"|"SGST"|"IGST"|"OTHER", "rate": number|null, "amount": number}],
 "tax_total": number|null, "total": number|null, "bank_account": str|null, "ifsc": str|null, "notes": str|null,
 "confidence": {field: number 0-1}, "evidence": {field: short snippet}}"""


def parse_json(text: str) -> dict:
    """Pull the JSON object out of a model reply, tolerating ```json fences or stray prose."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if fence:
        t = fence.group(1)
    elif not t.startswith("{"):
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON object in the model reply")
        t = t[start:end + 1]
    return json.loads(t)


def _images(path) -> list[bytes]:
    return [png_bytes(img) for img in render_pages(path, dpi=200)[:3]]


# ---------------------------------------------------------------- Gemini (free tier)
def _gemini(path, route: str, text: str) -> tuple[InvoiceExtraction, dict]:
    from google import genai
    from google.genai import types

    # Scans carry images and take longer; text PDFs should answer in seconds.
    client = genai.Client(http_options=types.HttpOptions(timeout=45_000 if route == "scan" else 30_000))
    base = dict(system_instruction=SYSTEM + "\n\n" + JSON_SHAPE, response_mime_type="application/json",
                temperature=0)
    # Reading an invoice is transcription, not reasoning: keep "thinking" low so replies come back fast.
    fast_cfg = types.GenerateContentConfig(**base, thinking_config=types.ThinkingConfig(
        thinking_level=types.ThinkingLevel.LOW))
    plain_cfg = types.GenerateContentConfig(**base)
    cfgs = {"use_fast": True}
    if route == "text":
        parts = [f"Invoice text (from a digital PDF):\n\n{text}"]
    else:
        parts = ["This invoice is a scanned image. Read it carefully; lower your confidence where print is unclear."]
        parts += [types.Part.from_bytes(data=b, mime_type="image/png") for b in _images(path)]

    used = {"model": config.GEMINI_MODEL}

    def once(model, extra):
        contents = parts + ([extra] if extra else [])
        if cfgs["use_fast"]:
            try:
                resp = client.models.generate_content(model=model, contents=contents, config=fast_cfg)
            except Exception as e:  # noqa: BLE001  a model that doesn't accept a thinking level: ask again without it
                if "thinking" not in str(e).lower() and "400" not in str(e):
                    raise
                cfgs["use_fast"] = False
                resp = client.models.generate_content(model=model, contents=contents, config=plain_cfg)
        else:
            resp = client.models.generate_content(model=model, contents=contents, config=plain_cfg)
        u = getattr(resp, "usage_metadata", None)
        usage = {"input_tokens": getattr(u, "prompt_token_count", None),
                 "output_tokens": getattr(u, "candidates_token_count", None)}
        return resp.text or "", usage

    def call(extra=None):
        """Busy or rate-limited (503/429): wait briefly and retry once, then try the backup model.
        Any other error (bad key, retired model) is raised at once so the local reader takes over."""
        models = [config.GEMINI_MODEL] + ([config.GEMINI_FALLBACK_MODEL] if config.GEMINI_FALLBACK_MODEL else [])
        last = None
        for i, model in enumerate(models):
            for attempt in range(2 if i == 0 else 1):
                try:
                    out = once(model, extra)
                    used["model"] = model
                    return out
                except Exception as e:  # noqa: BLE001
                    if not _is_temporary(e):
                        raise
                    last = e
                    if _is_timeout(e):
                        break  # this model is too slow right now: go straight to the backup model
                    if attempt == 0 and i == 0:
                        time.sleep(3)
        raise last

    raw, usage = call()
    try:
        return InvoiceExtraction.model_validate(parse_json(raw)), {"usage": usage, "retried": False,
                                                                     "model": used["model"]}
    except (ValidationError, ValueError) as e:
        raw, _ = call(f"Your previous reply was invalid ({str(e)[:300]}). Reply again with valid JSON only.")
        return InvoiceExtraction.model_validate(parse_json(raw)), {"usage": usage, "retried": True,
                                                                     "model": used["model"]}


def _is_timeout(e: Exception) -> bool:
    text = f"{type(e).__name__} {e}".lower()
    return "timeout" in text or "timed out" in text or "deadline" in text


def _is_temporary(e: Exception) -> bool:
    text = f"{type(e).__name__} {e}"
    return _is_timeout(e) or any(k in text for k in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED",
                                                     "overloaded", "high demand"))


# ---------------------------------------------------------------- Claude (Anthropic API)
TOOL = {
    "name": "record_invoice",
    "description": "Record the fields extracted from the invoice.",
    "input_schema": InvoiceExtraction.model_json_schema(),
}


def _claude(path, route: str, text: str) -> tuple[InvoiceExtraction, dict]:
    import anthropic

    client = anthropic.Anthropic(timeout=45.0, max_retries=1)  # fail fast in a live demo; local reader takes over
    if route == "text":
        content = [{"type": "text", "text": f"Invoice text (from a digital PDF):\n\n{text}"}]
    else:
        content = [{"type": "text", "text": "This invoice is a scanned image. Read it carefully; "
                                            "lower your confidence where print is unclear."}]
        for b in _images(path):
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": base64.b64encode(b).decode()}})

    def call(retry_note=None):
        msgs = [{"role": "user", "content": content}]
        if retry_note:
            msgs.append({"role": "user", "content": retry_note})
        resp = client.messages.create(model=config.LLM_MODEL, max_tokens=4000, system=SYSTEM, messages=msgs,
                                      tools=[TOOL], tool_choice={"type": "tool", "name": "record_invoice"})
        block = next(b for b in resp.content if b.type == "tool_use")
        return block.input, {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}

    raw, usage = call()
    try:
        return InvoiceExtraction.model_validate(raw), {"usage": usage, "retried": False}
    except ValidationError as e:
        raw, _ = call(f"Your previous output failed validation: {e}. Call record_invoice again with valid data.")
        return InvoiceExtraction.model_validate(raw), {"usage": usage, "retried": True}


def extract(path, route: str, text: str) -> tuple[InvoiceExtraction, dict]:
    p = config.provider()
    if p == "gemini":
        ext, meta = _gemini(path, route, text)
    elif p == "claude":
        ext, meta = _claude(path, route, text)
    else:
        raise RuntimeError("No LLM key configured (set GEMINI_API_KEY or ANTHROPIC_API_KEY)")
    return ext, {"model": config.model_name(), **meta, "provider": p}
