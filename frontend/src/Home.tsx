import { useEffect, useRef, useState } from "react";
import { api, money, Sample } from "./api";
import { Badge } from "./Dashboard";

export default function Home() {
  const [samples, setSamples] = useState<Sample[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetDone, setResetDone] = useState(false);
  const [runs, setRuns] = useState<any[]>([]);
  const loadRuns = () => api.runs().then(setRuns).catch(() => {});
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.samples().then(setSamples).catch((e) => setError(`Could not load samples: ${e.message}`));
    loadRuns();
  }, []);

  const go = (p: Promise<{ run_id: number }>, key: string) => {
    setBusy(key);
    setError(null);
    p.then((r) => (window.location.hash = `#/runs/${r.run_id}`))
      .catch((e) => setError(e.message))
      .finally(() => setBusy(null));
  };

  const onFile = (f: File | undefined) => {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".pdf")) {
      setError("That file is not a PDF. Upload the invoice as a PDF.");
      return;
    }
    go(api.upload(f), "upload");
  };

  const queue = runs.filter((r) => r.decision === "Hold for review");
  const last: Record<string, any> = {};
  for (const r of runs) if (!last[r.file_name]) last[r.file_name] = r; // runs come newest first

  const runAll = () => {
    setBusy("all");
    setError(null);
    api.runAll().then(() => (window.location.hash = "#/history"))
      .catch((e) => setError(e.message)).finally(() => setBusy(null));
  };

  return (
    <div className="home">
      <div>
        <h1>Run an invoice</h1>
        <p className="lede">
          Upload a vendor invoice, or pick one of the prepared samples. The checks run in order and each one shows
          what it found, so you can see exactly why an invoice was approved, held or rejected.
        </p>
        {error && <div className="error-banner">{error}</div>}

        {queue.length > 0 && (
          <section className="queue" aria-label="Invoices waiting for review">
            <h2>Waiting for your review <span className="count">{queue.length}</span></h2>
            {queue.map((r) => (
              <a className="queue-row" key={r.id} href={`#/runs/${r.id}`}>
                <span className="qv">{r.vendor ?? "Unknown vendor"}</span>
                <span className="qa">{money(r.total, r.currency)}</span>
                <span className="qr">{r.reason_summary}</span>
                <span className="qgo">Review</span>
              </a>
            ))}
          </section>
        )}

        <div
          className={`drop ${over ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); onFile(e.dataTransfer.files[0]); }}
        >
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" />
            <path d="M12 18v-6M9.5 14.5L12 12l2.5 2.5" />
          </svg>
          <p>Drop an invoice PDF here, or</p>
          <button className="btn primary" disabled={!!busy} onClick={() => input.current?.click()}>
            {busy === "upload" ? "Uploading…" : "Choose a file"}
          </button>
          <input ref={input} type="file" accept="application/pdf" hidden onChange={(e) => onFile(e.target.files?.[0])} />
        </div>

        <div className="samples-head">
          <h2>Prepared samples</h2>
          <button className="btn" disabled={!!busy} onClick={runAll}>
            {busy === "all" ? "Starting…" : "Reset and run all 8"}
          </button>
        </div>
        <div className="samples">
          {samples.map((s) => (
            <div className="sample" key={s.file}>
              <div>
                <div className="t">{s.title}</div>
                <div className="d">{s.description}</div>
                <div className="f">{s.file}</div>
              </div>
              <div className="sample-act">
                {last[s.file] && (
                  <a href={`#/runs/${last[s.file].id}`} title="Open the last run of this sample"><Badge run={last[s.file]} /></a>
                )}
                <button className="btn" disabled={!!busy} onClick={() => go(api.runSample(s.file), s.file)}>
                  {busy === s.file ? "Starting…" : "Run"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <aside className="aside">
        <h2>What happens to an invoice</h2>
        <ol>
          <li>Read it, from text or from a scan</li>
          <li>Check required fields and the arithmetic</li>
          <li>Confirm the vendor and their bank account</li>
          <li>Look for duplicates</li>
          <li>Match it to a purchase order, line by line</li>
          <li>Decide, explain why, and route it</li>
        </ol>
        <p>
          The AI model only reads the document. Every decision comes from rules your AP team can read and change.
        </p>
        <p className="muted" style={{ marginBottom: 8 }}>
          Some samples depend on earlier ones. Run them top to bottom after a reset.
        </p>
        <button className="btn" onClick={() => api.reset().then(() => { loadRuns(); setResetDone(true); setTimeout(() => setResetDone(false), 2000); })}>
          {resetDone ? "Demo data reset" : "Reset demo data"}
        </button>
      </aside>
    </div>
  );
}
