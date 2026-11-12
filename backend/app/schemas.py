"""The one extraction schema. Both routes (text PDF, scanned image) and both modes (LLM, local) must fill it,
so nothing downstream cares how the invoice was read."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

KEY_FIELDS = ["vendor_name", "vendor_gstin", "invoice_number", "invoice_date", "po_reference",
              "subtotal", "tax_total", "total", "bank_account", "ifsc"]


class LineItem(BaseModel):
    description: str
    hsn: Optional[str] = None
    quantity: Optional[float] = None
    uom: Optional[str] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class TaxLine(BaseModel):
    type: Literal["CGST", "SGST", "IGST", "OTHER"]
    rate: Optional[float] = Field(None, description="Percent, e.g. 9 for 9%")
    amount: float


class InvoiceExtraction(BaseModel):
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    buyer_gstin: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = Field(None, description="ISO format YYYY-MM-DD")
    po_reference: Optional[str] = None
    currency: str = "INR"
    line_items: list[LineItem] = []
    subtotal: Optional[float] = None
    tax_lines: list[TaxLine] = []
    tax_total: Optional[float] = None
    total: Optional[float] = None
    bank_account: Optional[str] = None
    ifsc: Optional[str] = None
    notes: Optional[str] = Field(None, description="Anything unusual, e.g. a notice about changed bank details")
    confidence: dict[str, float] = Field(default_factory=dict, description="0-1 per key field")
    evidence: dict[str, str] = Field(default_factory=dict, description="Text snippet each key field was read from")


class ExtractionResult(BaseModel):
    data: InvoiceExtraction
    route: Literal["text", "scan"]
    mode: Literal["llm", "local"]
    provider: Optional[str] = None          # gemini | claude when an LLM read it
    fallback_reason: Optional[str] = None   # set when the LLM was wanted but failed and the local reader took over
    cached: bool = False                    # LLM result reused for an identical file (saves quota, stable demos)
    checks: list[dict] = []          # internal consistency checks used to calibrate confidence
    missing_fields: list[str] = []   # absent from a readable document (=> genuinely missing)
    unreadable_fields: list[str] = []  # not found on a scan (=> may be present, needs a human)
    low_confidence_fields: list[str] = []
    raw_text: str = ""
