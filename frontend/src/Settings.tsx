import { useEffect, useState } from "react";
import { api } from "./api";

const FIELDS: { key: string; label: string; help: string; unit: string; step: number }[] = [
  { key: "price_tolerance_pct", label: "Price tolerance", unit: "%", step: 0.1,
    help: "How far a line or total may differ from the purchase order and still pass." },
  { key: "price_tolerance_abs", label: "Tolerance cap", unit: "₹", step: 50,
    help: "The most a difference may be in rupees, whatever the percentage allows. The lower limit applies." },
  { key: "confidence_floor", label: "Confidence needed to skip review", unit: "0–1", step: 0.05,
    help: "Any key field read below this goes to a person." },
  { key: "duplicate_amount_pct", label: "Duplicate amount window", unit: "%", step: 0.5,
    help: "Invoices from one vendor this close in amount are treated as possible duplicates..." },
  { key: "duplicate_window_days", label: "Duplicate date window", unit: "days", step: 1,
    help: "...when they are also this many days apart or fewer." },
  { key: "manual_minutes_per_invoice", label: "Minutes to check one invoice by hand", unit: "min", step: 1,
    help: "Used for \"Time saved\" on the History page." },
  { key: "demo_pacing_ms", label: "Demo pacing", unit: "ms", step: 50,
    help: "Minimum time each check stays on screen in the live view. Set to 0 to run at full speed." },
];

export default function Settings() {
  const [cfg, setCfg] = useState<Record<string, number> | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ins, setIns] = useState<any>(null);
  const loadIns = () => api.insights().then(setIns).catch(() => {});
  useEffect(() => { loadIns(); }, []);

  useEffect(() => {
    api.getConfig().then((c) => {
      setCfg(c);
      setDraft(Object.fromEntries(Object.entries(c).map(([k, v]) => [k, String(v)])));
    }).catch((e) => setError(e.message));
  }, []);

  const save = () => {
    const out: Record<string, number> = {};
    for (const f of FIELDS) {
      const v = Number(draft[f.key]);
      if (Number.isNaN(v) || v < 0) {
        setError(`${f.label} must be a number of zero or more.`);
        return;
      }
      out[f.key] = v;
    }
    api.putConfig(out).then((c) => {
      setCfg(c);
      loadIns();
      setError(null);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    }).catch((e) => setError(e.message));
  };

  if (!cfg) return <p className="muted">{error ?? "Loading settings…"}</p>;
  const dirty = FIELDS.some((f) => String(cfg[f.key]) !== draft[f.key]);

  return (
    <div className="settings">
      <h1>Rule settings</h1>
      <p className="lede">
        The limits the checks use. Changes apply to the next invoice you run; earlier decisions stay as they were.
      </p>
      {error && <div className="error-banner">{error}</div>}
      <form onSubmit={(e) => { e.preventDefault(); save(); }}>
        {FIELDS.map((f) => (
          <div className="setting" key={f.key}>
            <label htmlFor={f.key}>
              <span className="sl">{f.label}</span>
              <span className="sh">{f.help}</span>
            </label>
            <div className="sv">
              <input id={f.key} type="number" step={f.step} min={0} value={draft[f.key] ?? ""}
                onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
              <span>{f.unit}</span>
            </div>
          </div>
        ))}
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 20 }}>
          <button className="btn primary" type="submit" disabled={!dirty}>Save settings</button>
          {saved && <span className="muted">Settings saved</span>}
        </div>
      </form>

      <section className="insights-rev" aria-labelledby="ih">
        <h2 id="ih">What reviewers' decisions suggest</h2>
        <p className="lede">
          Every held invoice a person approves or rejects is a signal. If people keep approving invoices held for the
          same reason, that limit may be too strict.
        </p>
        {!ins || ins.rules.length === 0 ? (
          <p className="muted">No invoices have been held yet. Run the samples, then approve or reject the held ones.</p>
        ) : (
          <>
            <table className="vendors">
              <thead>
                <tr><th>Held because of</th><th className="num">Held</th><th className="num">Approved by a person</th>
                  <th className="num">Rejected by a person</th><th className="num">Still waiting</th></tr>
              </thead>
              <tbody>
                {ins.rules.map((r: any) => (
                  <tr key={r.rule}>
                    <td>{r.name}</td><td className="num">{r.held}</td><td className="num">{r.approved}</td>
                    <td className="num">{r.rejected}</td><td className="num">{r.waiting}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {ins.rules.filter((r: any) => r.suggestion || r.note).map((r: any) => (
              <div key={r.rule} className={`suggest ${r.suggestion ? "" : "caution"}`}>
                <b>{r.name}.</b> {r.suggestion ? r.suggestion.text : r.note}
                {r.suggestion && (
                  <button className="btn" onClick={() => setDraft({ ...draft, [r.suggestion.setting]: String(r.suggestion.to) })}>
                    Use {r.suggestion.to}
                  </button>
                )}
              </div>
            ))}
            {!ins.rules.some((r: any) => r.suggestion) && (
              <p className="muted">
                No change suggested yet: a suggestion appears once reviewers have decided at least two invoices held for
                the same adjustable reason, and approved most of them.
              </p>
            )}
          </>
        )}
      </section>
    </div>
  );
}
