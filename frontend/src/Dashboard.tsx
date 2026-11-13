import { useEffect, useMemo, useState } from "react";
import { api, decisionLabel, DECISION_TONE, inr, money, timeAgo } from "./api";

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

function duration(min: number): string {
  if (!min) return "0 min";
  const h = Math.floor(min / 60), m = min % 60;
  return h ? `${h} h${m ? ` ${m} min` : ""}` : `${m} min`;
}

const DAY = 86400000;
function dueInfo(due: string | null): { days: number; label: string; tone: string } | null {
  if (!due) return null;
  const today = new Date(new Date().toDateString()).getTime();
  const days = Math.round((new Date(due + "T00:00:00").getTime() - today) / DAY);
  if (days < 0) return { days, label: `Overdue by ${-days} day${days === -1 ? "" : "s"}`, tone: "reject" };
  if (days === 0) return { days, label: "Due today", tone: "hold" };
  if (days <= 7) return { days, label: `Due in ${days} day${days === 1 ? "" : "s"}`, tone: "hold" };
  return { days, label: `Due in ${days} days`, tone: "" };
}

export default function Dashboard() {
  const [runs, setRuns] = useState<any[] | null>(null);
  const [stats, setStats] = useState<any>(null);
  const [filter, setFilter] = useState("all");
  const [vendor, setVendor] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [cfgMinutes, setCfgMinutes] = useState(8);
  useEffect(() => { api.getConfig().then((c) => setCfgMinutes(c.manual_minutes_per_invoice ?? 8)).catch(() => {}); }, []);

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

  const done = (runs ?? []).filter((r) => r.status === "done" && r.decision);
  const segs = [
    { key: "approve", label: "Approved", n: done.filter((r) => r.decision === "Approve").length },
    { key: "note", label: "Approved with note", n: done.filter((r) => r.decision === "Approve with note").length },
    { key: "hold", label: "Waiting for review", n: done.filter((r) => r.decision === "Hold for review").length },
    { key: "reject", label: "Rejected", n: done.filter((r) => r.decision === "Reject").length },
  ];
  const byVendor = useMemo(() => {
    const m = new Map<string, { vendor: string; n: number; value: number; other: Record<string, number>; ok: number; hold: number; rej: number }>();
    for (const r of done) {
      const k = r.vendor ?? "Unknown vendor";
      const v = m.get(k) ?? { vendor: k, n: 0, value: 0, other: {} as Record<string, number>, ok: 0, hold: 0, rej: 0 };
      v.n += 1;
      const cur: string = r.currency || "INR";
      if (cur === "INR") v.value += r.total ?? 0;
      else if (r.total) v.other[cur] = (v.other[cur] ?? 0) + r.total;
      if (r.decision === "Hold for review") v.hold += 1;
      else if (r.decision === "Reject") v.rej += 1;
      else v.ok += 1;
      m.set(k, v);
    }
    return Array.from(m.values()).sort((a, b) => b.value - a.value);
  }, [runs]); // eslint-disable-line react-hooks/exhaustive-deps

  const payable = useMemo(() => (runs ?? [])
    .filter((r) => r.status === "done" && r.due_date && (r.decision === "Approve" || r.decision === "Approve with note"))
    .map((r) => ({ r, d: dueInfo(r.due_date) }))
    .sort((a, b) => a.r.due_date.localeCompare(b.r.due_date)), [runs]);

  if (error) return <div className="error-banner">{error}</div>;
  if (!runs) return <p className="muted">Loading history…</p>;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Invoice history</h1>
          <p className="lede">Every invoice the process has handled, what it decided, and why.</p>
        </div>
        {runs.length > 0 && <a className="btn" href="/api/runs.csv" download>Download CSV</a>}
      </div>

      {stats && stats.invoices > 0 && (
        <dl className="ledger">
          <div><dt>Invoices processed</dt><dd>{stats.invoices}</dd></div>
          <div>
            <dt>Total value (INR)</dt><dd>{inr(stats.value)}</dd>
            {stats.other_currencies && Object.keys(stats.other_currencies).length > 0 && (
              <p className="other-cur" title="Not converted to INR: no exchange rates are applied">
                + {Object.entries(stats.other_currencies as Record<string, number>).map(([c, x]) => money(x, c)).join(", ")} in other currencies
              </p>
            )}
          </div>
          <div>
            <dt>Decided without a person</dt><dd>{stats.auto_decided_pct}%</dd>
            <span className="meter" aria-hidden="true"><span style={{ width: `${stats.auto_decided_pct}%` }} /></span>
          </div>
          <div className={stats.waiting_review ? "attention" : ""}>
            <dt>Waiting for review</dt><dd>{stats.waiting_review}</dd>
            {stats.waiting_review > 0 && (
              <button className="linkbtn small" onClick={() => setFilter("review")}>Show them</button>
            )}
          </div>
          <div>
            <dt>Time saved</dt><dd>{duration(stats.minutes_saved)}</dd>
            <p className="other-cur" title="Change the minutes per invoice in Rule settings">
              {stats.minutes_saved ? `at ${cfgMinutes} min per invoice checked by hand` : "Nothing decided automatically yet"}
            </p>
          </div>
        </dl>
      )}

      {done.length > 0 && (
        <div className="insights">
          <section className="panel" aria-label="Decisions">
            <h2>Decisions</h2>
            <div className="stack" role="img"
              aria-label={segs.filter((s) => s.n).map((s) => `${s.label}: ${s.n}`).join(", ")}>
              {segs.filter((s) => s.n > 0).map((s) => (
                <div key={s.key} className={`seg ${s.key}`} style={{ flexGrow: s.n }}
                  title={`${s.label}: ${s.n} of ${done.length} (${Math.round((100 * s.n) / done.length)}%)`} />
              ))}
            </div>
            <ul className="legend">
              {segs.map((s) => (
                <li key={s.key}>
                  <i className={`sw ${s.key}`} />
                  <span>{s.label}</span>
                  <b>{s.n}</b>
                  <span className="muted">{done.length ? Math.round((100 * s.n) / done.length) : 0}%</span>
                </li>
              ))}
            </ul>
          </section>
          <section className="panel" aria-label="By vendor">
            <h2>By vendor</h2>
            <table className="vendors">
              <thead>
                <tr><th>Vendor</th><th className="num">Invoices</th><th className="num">Value</th><th>Outcome</th></tr>
              </thead>
              <tbody>
                {byVendor.map((v) => (
                  <tr key={v.vendor}>
                    <td>{v.vendor}</td>
                    <td className="num">{v.n}</td>
                    <td className="num">
                      {(v.value > 0 || Object.keys(v.other).length === 0) && <div>{inr(v.value)}</div>}
                      {Object.entries(v.other).map(([c, x]) => <div key={c}>{money(x, c)}</div>)}
                    </td>
                    <td className="muted">
                      {[v.ok && `${v.ok} approved`, v.hold && `${v.hold} waiting`, v.rej && `${v.rej} rejected`]
                        .filter(Boolean).join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}

      {payable.length > 0 && (
        <section className="panel payments" aria-label="Payments coming up">
          <div className="panel-head">
            <h2>Payments coming up</h2>
            <span className="muted">Approved invoices, due date from each vendor's payment terms</span>
          </div>
          <table className="vendors">
            <thead>
              <tr><th>Due</th><th>Vendor</th><th>Invoice</th><th className="num">To pay</th><th></th></tr>
            </thead>
            <tbody>
              {payable.slice(0, 6).map(({ r, d }) => (
                <tr key={r.id}>
                  <td>{new Date(r.due_date + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</td>
                  <td>{r.vendor}</td>
                  <td><a href={`#/runs/${r.id}`}>{r.invoice_no ?? `Run #${r.id}`}</a></td>
                  <td className="num">{money(r.approved_amount ?? r.total, r.currency)}</td>
                  <td>{d && <span className={`due ${d.tone}`}>{d.label}</span>}
                    {r.terms_days != null && <span className="muted"> · {r.terms_days}-day terms</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {payable.length > 6 && <p className="muted" style={{ margin: "8px 0 0" }}>+ {payable.length - 6} more in the CSV</p>}
        </section>
      )}

      {runs.length === 0 ? (
        <div className="empty">
          <p>No invoices yet. Run one to see it here.</p>
          <a className="btn primary" href="#/run">Run an invoice</a>
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
                  <tr key={r.id} className={`tone-${r.status === "error" ? "reject" : r.decision ? DECISION_TONE[r.decision] : "pending"}`}
                    onClick={() => (window.location.hash = `#/runs/${r.id}`)}>
                    <td><a href={`#/runs/${r.id}`} onClick={(e) => e.stopPropagation()}>#{r.id}</a></td>
                    <td className="muted">{timeAgo(r.started_at)}</td>
                    <td className="vendor-cell">{r.vendor ?? <span className="muted">Unknown</span>}</td>
                    <td>{r.invoice_no ?? <span className="muted">none</span>}</td>
                    <td>{r.po_number ? <>{r.po_number}{r.po_inferred && <span className="muted"> (suggested)</span>}</> : <span className="muted">none</span>}</td>
                    <td className="num amt">{money(r.total, r.currency)}
                      {r.approved_amount != null && <div className="part">{money(r.approved_amount, r.currency)} approved</div>}</td>
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
