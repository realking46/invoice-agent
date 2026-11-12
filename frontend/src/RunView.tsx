import { useEffect, useMemo, useRef, useState } from "react";
import { api, decisionLabel, DECISION_TONE, inr, Stage, STAMP_WORD } from "./api";
import { AuditTrail, ReviewPanel } from "./Review";
import Evidence from "./Evidence";
import Why from "./Why";

export const STAGES: { key: string; label: string }[] = [
  { key: "ingest", label: "Receive file" },
  { key: "classify", label: "Check document type" },
  { key: "extract", label: "Read the invoice" },
  { key: "validate", label: "Validate fields and figures" },
  { key: "vendor", label: "Check vendor and bank" },
  { key: "duplicate", label: "Look for duplicates" },
  { key: "po_match", label: "Match to purchase order" },
  { key: "decide", label: "Decide" },
  { key: "output", label: "Record and route" },
];

const blank = (): Stage[] => STAGES.map((s) => ({ ...s, status: "waiting" }));

function Icon({ status, n }: { status: string; n: number }) {
  const p = { width: 14, height: 14, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 3,
    strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  if (status === "pass" || status === "note") return <svg {...p}><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>;
  if (status === "warn") return <svg {...p}><path d="M12 7v6M12 17h.01" /></svg>;
  if (status === "fail" || status === "error") return <svg {...p}><path d="M7 7l10 10M17 7L7 17" /></svg>;
  return <span>{n}</span>;
}

const STATUS_WORD: Record<string, string> = {
  waiting: "waiting", running: "running", pass: "passed", note: "passed with a note", warn: "needs review",
  fail: "failed", skip: "not applicable", error: "error",
};

export default function RunView({ id }: { id: number }) {
  const [stages, setStages] = useState<Stage[]>(blank);
  const [open, setOpen] = useState<string | null>(null);
  const [decision, setDecision] = useState<any>(null);
  const [action, setAction] = useState<any>(null);
  const [run, setRun] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [audit, setAudit] = useState<any[]>([]);
  const [boxes, setBoxes] = useState<{ x: number; y: number; w: number; h: number; label: string }[]>([]);
  const [tech, setTech] = useState(() => {
    try { return localStorage.getItem("tech") === "1"; } catch { return false; }
  });
  const userOpened = useRef(false);

  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;
    setStages(blank());
    setDecision(null);
    setAction(null);
    setOpen(null);
    setBoxes([]);
    userOpened.current = false;

    const loadStatic = () =>
      api.run(id).then((r) => {
        if (cancelled) return;
        setRun(r.run);
        setAudit(r.audit ?? []);
        const byKey: Record<string, any> = Object.fromEntries(r.steps.map((s: any) => [s.stage, s]));
        setStages(STAGES.map((s) => {
          const st = byKey[s.key];
          return st ? { ...s, status: st.status, summary: st.summary, duration_ms: st.duration_ms, detail: st.detail }
            : { ...s, status: r.run.status === "error" ? "skip" : "waiting" };
        }));
        if (byKey.decide) setDecision(byKey.decide.detail);
        if (byKey.output) setAction(byKey.output.detail.next_action);
        if (byKey.error) setError(byKey.error.summary);
        if (byKey.decide) api.highlights(id).then((h) => { if (!cancelled) setBoxes(h.boxes); }).catch(() => {});
      });

    api.run(id).then((r) => {
      if (cancelled) return;
      setRun(r.run);
      if (r.run.status === "done" || r.run.status === "error") return loadStatic();
      es = new EventSource(`/api/runs/${id}/stream`);
      es.onmessage = (m) => {
        const e = JSON.parse(m.data);
        if (e.type === "stage_started") {
          setStages((prev) => prev.map((s) => (s.key === e.stage ? { ...s, status: "running" } : s)));
        } else if (e.type === "stage_finished") {
          setStages((prev) => prev.map((s) => s.key === e.stage
            ? { ...s, status: e.status, summary: e.summary, duration_ms: e.duration_ms, detail: e.detail } : s));
        } else if (e.type === "run_finished") {
          es?.close();
          if (e.status === "error") setError(e.error);
          loadStatic();
        }
      };
      es.onerror = () => {
        es?.close();
        loadStatic();
      };
    }).catch((e) => setError(String(e.message ?? e)));
    return () => {
      cancelled = true;
      es?.close();
    };
  }, [id]);

  // When the run finishes, open the stage that drove the decision (unless the user already opened one)
  useEffect(() => {
    if (!decision || userOpened.current) return;
    const tone = decision.decision;
    const target = tone === "Approve" ? null
      : stages.find((s) => s.key !== "decide" && s.key !== "output" &&
        ((tone === "Reject" && s.status === "fail") || (tone === "Hold for review" && s.status === "warn") ||
          (tone === "Approve with note" && s.status === "note")))?.key;
    if (target) setOpen(target);
  }, [decision]); // eslint-disable-line react-hooks/exhaustive-deps

  const extract = stages.find((s) => s.key === "extract")?.detail;
  const fields = extract?.fields ?? {};
  const outputDetail = stages.find((s) => s.key === "output")?.detail;
  const reviewed = !!run?.reviewed_by;
  const finalDecision: string | undefined = reviewed ? run.decision : decision?.decision;
  const tone = finalDecision ? DECISION_TONE[finalDecision] : null;
  const finished = stages.filter((s) => !["waiting", "running"].includes(s.status)).length;
  const totalMs = useMemo(() => stages.reduce((a, s) => a + (s.duration_ms ?? 0), 0), [stages]);

  return (
    <>
      <div className="runhead">
        <div>
          <p className="muted" style={{ margin: "0 0 2px" }}>Run #{id} — {run?.file_name ?? "…"}</p>
          <h1>{outputDetail?.vendor ?? fields.vendor_name ?? "Reading invoice…"}</h1>
        </div>
        <dl className="facts">
          <div><dt>Invoice</dt><dd>{fields.invoice_number ?? "—"}</dd></div>
          <div><dt>Date</dt><dd>{fields.invoice_date ?? "—"}</dd></div>
          <div><dt>Purchase order</dt><dd>{fields.po_reference ?? (outputDetail?.po ? `${outputDetail.po} (suggested)` : "—")}</dd></div>
          <div><dt>Total</dt><dd>{fields.total != null ? inr(fields.total) : extract ? "Not on invoice" : "—"}</dd></div>
        </dl>
        <div className="actions">
          <a className="btn quiet" href="#/history">All invoices</a>
          <a className="btn" href="#/">Run another invoice</a>
        </div>
      </div>

      {error && <div className="error-banner">Processing stopped: {error}</div>}

      <div className="runview">
        <section aria-label="Processing steps">
          <ol className="trail" aria-live="polite">
            {stages.map((s, i) => (
              <li key={s.key} className={`step ${s.status}`}>
                <span className="icon"><Icon status={s.status} n={i + 1} /></span>
                <button
                  className="step-head"
                  disabled={!s.detail}
                  aria-expanded={open === s.key}
                  onClick={() => {
                    userOpened.current = true;
                    setOpen(open === s.key ? null : s.key);
                  }}
                >
                  <span className="step-name">{s.label}</span>
                  <span className="step-time">
                    {s.status === "running" ? "working…" : s.duration_ms !== undefined ? `${s.duration_ms} ms` : ""}
                  </span>
                  <span className="step-sum">
                    <span className="sr-only">{STATUS_WORD[s.status]}: </span>
                    {s.summary ?? (s.status === "waiting" ? "" : "")}
                  </span>
                </button>
                {open === s.key && s.detail && (
                  <div className="evidence"><Evidence stage={s} tech={tech} /></div>
                )}
              </li>
            ))}
          </ol>
          <label className="techtoggle">
            <input type="checkbox" checked={tech} onChange={(e) => {
              setTech(e.target.checked);
              try { localStorage.setItem("tech", e.target.checked ? "1" : "0"); } catch {}
            }} />
            Show rule IDs and technical details
          </label>
        </section>

        <figure className="doc" style={{ margin: 0 }}>
          {decision && tone && (
            <div className={`decision ${tone}`} role="status">
              <p className="verdict">{reviewed ? decisionLabel(run) : decision.decision}</p>
              {reviewed ? (
                <>
                  <p className="why">{run.review_note}</p>
                  <p className="overridden">The rules held it: {decision.summary}</p>
                </>
              ) : (
                <p className="why">{decision.summary}</p>
              )}
              <Why decision={decision} stages={stages} tech={tech} />
              {action && !reviewed && (
                <dl className="next">
                  <dt>Next step</dt><dd>{action.action}</dd>
                  {action.owner && (<><dt>Owner</dt><dd>{action.owner}</dd></>)}
                  <dt>Confidence</dt><dd>{decision.confidence?.toFixed(2)}</dd>
                </dl>
              )}
              {!reviewed && run?.decision === "Hold for review" && (
                <ReviewPanel runId={id} onDone={(r) => { setRun(r.run); setAudit(r.audit ?? []); }} />
              )}
              {action?.vendor_email && !reviewed && (
                <div className="email">
                  <header>
                    <span><b>Draft to vendor:</b> {action.vendor_email.subject}</span>
                    <button className="btn quiet" onClick={() => {
                      navigator.clipboard?.writeText(`${action.vendor_email.subject}\n\n${action.vendor_email.body}`);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 1500);
                    }}>{copied ? "Copied" : "Copy email"}</button>
                  </header>
                  <pre>{action.vendor_email.body}</pre>
                </div>
              )}
            </div>
          )}
          <div className="sheet">
            <img src={`/api/runs/${id}/page/1.png`} alt={`First page of ${run?.file_name ?? "the invoice"}`} />
            {decision && boxes.map((b, i) => (
              <div key={i} className={`hl ${DECISION_TONE[decision.decision]}`} title={b.label}
                style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` }} />
            ))}
            {decision && tone && (
              <div className={`stamp ${tone}`} aria-hidden="true">
                {STAMP_WORD[finalDecision!]}
              </div>
            )}
          </div>
          <figcaption>
            <span>
              {boxes.length
                ? `Marked on the invoice: ${Array.from(new Set(boxes.map((b) => b.label))).join("; ")}`
                : `${finished} of ${STAGES.length} checks done`}
            </span>
            <span>{totalMs ? `${(totalMs / 1000).toFixed(2)} s processing` : ""}</span>
          </figcaption>
          {decision && <AuditTrail events={audit} />}
        </figure>
      </div>
    </>
  );
}
