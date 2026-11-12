import { useEffect, useMemo, useState } from "react";
import { api, decisionLabel, DECISION_TONE, inr, timeAgo } from "./api";

const FILTERS: { key: string; label: string; match: (r: any) => boolean }[] = [
  { key: "all", label: "All", match: () => true },
  { key: "review", label: "Waiting for review", match: (r) => r.decision === "Hold for review" },
  { key: "approved", label: "Approved", match: (r) => r.decision === "Approve" || r.decision === "Approve with note" },
  { key: "rejected", label: "Rejected", match: (r) => r.decision === "Reject" },
  { key: "reviewed", label: "Reviewed by a person", match: (r) => !!r.reviewed_by },
];

export function Badge({ run }: { run: any }) {
  const tone = run.status === "error" ? "reject" : run.decision ? DECISION_TONE[run.decision] : "pending";
  return <span className={`badge ${tone}`}>{decisionLabel(run)}</span>;
}

export default function Dashboard() {
  const [runs, setRuns] = useState<any[] | null>(null);
  const [stats, setStats] = useState<any>(null);
  const [filter, setFilter] = useState("all");
  const [vendor, setVendor] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let timer: number | undefined;
    const load = () =>
      Promise.all([api.runs(), api.stats()])
        .then(([r, s]) => {
          setRuns(r);
          setStats(s);
          setError(null);
          if (r.some((x) => x.status === "queued" || x.status === "running")) timer = window.setTimeout(load, 1500);
        })
        .catch((e) => setError(`Could not load history: ${e.message}`));
    load();
    return () => window.clearTimeout(timer);
  }, []);

  const vendors = useMemo(() => Array.from(new Set((runs ?? []).map((r) => r.vendor).filter(Boolean))).sort(), [runs]);
  const shown = useMemo(() => {
    const f = FILTERS.find((x) => x.key === filter)!;
    const needle = q.trim().toLowerCase();
    return (runs ?? []).filter((r) => f.match(r) && (!vendor || r.vendor === vendor) &&
      (!needle || [r.invoice_no, r.file_name, r.po_number].some((v) => v && String(v).toLowerCase().includes(needle))));
  }, [runs, filter, vendor, q]);

  if (error) return <div className="error-banner">{error}</div>;
  if (!runs) return <p className="muted">Loading history…</p>;

  return (
    <>
      <h1>Invoice history</h1>
      <p className="lede">Every invoice the process has handled, what it decided, and why.</p>

      {stats && stats.invoices > 0 && (
        <dl className="ledger">
          <div><dt>Invoices processed</dt><dd>{stats.invoices}</dd></div>
          <div><dt>Total value</dt><dd>{inr(stats.value)}</dd></div>
          <div><dt>Decided without a person</dt><dd>{stats.auto_decided_pct}%</dd></div>
          <div className={stats.waiting_review ? "attention" : ""}>
            <dt>Waiting for review</dt><dd>{stats.waiting_review}</dd>
          </div>
          <div><dt>Average processing time</dt><dd>{(stats.avg_processing_ms / 1000).toFixed(2)} s</dd></div>
        </dl>
      )}

      {runs.length === 0 ? (
        <div className="empty">
          <p>No invoices yet. Run one to see it here.</p>
          <a className="btn primary" href="#/">Run an invoice</a>
        </div>
      ) : (
        <>
          <div className="toolbar">
            <div className="tabs" role="tablist" aria-label="Filter by decision">
              {FILTERS.map((f) => {
                const n = runs.filter(f.match).length;
                return (
                  <button key={f.key} role="tab" aria-selected={filter === f.key} className="tab"
                    onClick={() => setFilter(f.key)}>
                    {f.label} <span className="count">{n}</span>
                  </button>
                );
              })}
            </div>
            <div className="filters">
              <label className="sr-only" htmlFor="vendor">Vendor</label>
              <select id="vendor" value={vendor} onChange={(e) => setVendor(e.target.value)}>
                <option value="">All vendors</option>
                {vendors.map((v) => <option key={v}>{v}</option>)}
              </select>
              <label className="sr-only" htmlFor="q">Search</label>
              <input id="q" type="search" placeholder="Search invoice or PO number" value={q}
                onChange={(e) => setQ(e.target.value)} />
            </div>
          </div>

          <div className="tablewrap">
            <table className="runs">
              <thead>
                <tr>
                  <th>Run</th><th>Received</th><th>Vendor</th><th>Invoice</th><th>PO</th>
                  <th className="num">Amount</th><th>Decision</th><th>Why</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id} onClick={() => (window.location.hash = `#/runs/${r.id}`)}>
                    <td><a href={`#/runs/${r.id}`} onClick={(e) => e.stopPropagation()}>#{r.id}</a></td>
                    <td className="muted">{timeAgo(r.started_at)}</td>
                    <td>{r.vendor ?? <span className="muted">Unknown</span>}</td>
                    <td>{r.invoice_no ?? <span className="muted">none</span>}</td>
                    <td>{r.po_number ? <>{r.po_number}{r.po_inferred && <span className="muted"> (suggested)</span>}</> : <span className="muted">none</span>}</td>
                    <td className="num">{inr(r.total)}</td>
                    <td><Badge run={r} /></td>
                    <td className="why">{r.reviewed_by ? `${r.review_note} (${r.reviewed_by})` : r.reason_summary}</td>
                  </tr>
                ))}
                {shown.length === 0 && (
                  <tr className="none"><td colSpan={8}>No invoices match these filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
