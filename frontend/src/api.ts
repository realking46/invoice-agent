export type StageStatus = "waiting" | "running" | "pass" | "note" | "warn" | "fail" | "skip" | "error";

export interface Stage {
  key: string;
  label: string;
  status: StageStatus;
  summary?: string;
  duration_ms?: number;
  detail?: any;
  progress?: string[];     // live lines while a slow step works ("Gemini is busy; retrying…")
  startedAt?: number;      // ms timestamp, for the elapsed-time counter
}

export interface Sample {
  file: string;
  title: string;
  description: string;
}

export const DECISION_TONE: Record<string, "approve" | "note" | "hold" | "reject"> = {
  Approve: "approve",
  "Approve with note": "note",
  "Hold for review": "hold",
  Reject: "reject",
};

export const STAMP_WORD: Record<string, string> = {
  Approve: "Approved",
  "Approve with note": "Approved",
  "Hold for review": "On hold",
  Reject: "Rejected",
};

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  health: () => fetch("/api/health").then((r) => json<{ extractor: string; provider: string | null; model: string | null }>(r)),
  samples: () => fetch("/api/samples").then((r) => json<Sample[]>(r)),
  runSample: (file: string) =>
    fetch(`/api/runs/sample/${encodeURIComponent(file)}`, { method: "POST" }).then((r) =>
      json<{ run_id: number; stages: { key: string; label: string }[] }>(r)
    ),
  upload: (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    return fetch("/api/runs", { method: "POST", body: fd }).then((r) =>
      json<{ run_id: number; stages: { key: string; label: string }[] }>(r)
    );
  },
  run: (id: number) => fetch(`/api/runs/${id}`).then((r) => json<any>(r)),
  runs: () => fetch("/api/runs").then((r) => json<any[]>(r)),
  reset: () => fetch("/api/reset", { method: "POST" }).then((r) => json<any>(r)),
  stats: () => fetch("/api/stats").then((r) => json<any>(r)),
  runAll: () => fetch("/api/runs/samples/all", { method: "POST" }).then((r) => json<{ run_ids: number[] }>(r)),
  highlights: (id: number) =>
    fetch(`/api/runs/${id}/highlights`).then((r) =>
      json<{ boxes: { x: number; y: number; w: number; h: number; label: string; rule: string }[] }>(r)),
  review: (id: number, action: "approve" | "reject", note: string, reviewer: string) =>
    fetch(`/api/runs/${id}/review`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action, note, reviewer }),
    }).then((r) => json<any>(r)),
  getConfig: () => fetch("/api/config").then((r) => json<Record<string, number>>(r)),
  putConfig: (c: Record<string, number>) =>
    fetch("/api/config", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(c) })
      .then((r) => json<Record<string, number>>(r)),
};

export function inr(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  return "₹" + x.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

export function fieldLabel(k: string): string {
  const map: Record<string, string> = {
    vendor_name: "Vendor",
    vendor_gstin: "Vendor GSTIN",
    invoice_number: "Invoice number",
    invoice_date: "Invoice date",
    po_reference: "PO reference",
    subtotal: "Taxable value",
    tax_total: "Tax",
    total: "Grand total",
    bank_account: "Bank account",
    ifsc: "IFSC",
    line_items: "Line items",
    notes: "Notes",
  };
  return map[k] ?? k.replace(/_/g, " ");
}

export function decisionLabel(run: { decision?: string | null; reviewed_by?: string | null; status?: string }): string {
  if (run.status === "error") return "Failed";
  if (!run.decision) return run.status === "done" ? "—" : "Processing";
  if (run.reviewed_by) return run.decision === "Approve" ? "Approved by reviewer" : "Rejected by reviewer";
  return { Approve: "Approved", "Approve with note": "Approved with note", "Hold for review": "Waiting for review",
    Reject: "Rejected" }[run.decision] ?? run.decision;
}

export function timeAgo(iso: string): string {
  const t = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime();
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(t).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
