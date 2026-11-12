import { fieldLabel, inr, Stage } from "./api";

const MONEY = new Set(["subtotal", "tax_total", "total"]);

function Conf({ v }: { v: number | undefined }) {
  const c = v ?? 0;
  const cls = c === 0 ? "zero" : c < 0.8 ? "low" : "";
  return (
    <span className={`conf ${cls}`} title={`Confidence ${c.toFixed(2)}`}>
      <i>
        <b style={{ width: `${Math.round(c * 100)}%` }} />
      </i>
      {c.toFixed(2)}
    </span>
  );
}

function fmt(k: string, v: any) {
  if (v === null || v === undefined || v === "") return <span className="muted">not found</span>;
  if (MONEY.has(k)) return inr(v);
  return String(v);
}

function ExtractEvidence({ d }: { d: any }) {
  const order = ["vendor_name", "vendor_gstin", "invoice_number", "invoice_date", "po_reference", "subtotal",
    "tax_total", "total", "bank_account", "ifsc"];
  const flagged = new Set([...(d.low_confidence_fields ?? []), ...(d.missing_fields ?? []), ...(d.unreadable_fields ?? [])]);
  return (
    <>
      <h3>
        Fields read {d.route === "scan" ? "from the scanned image" : "from the PDF text"} (
        {d.mode === "llm" ? `${d.provider === "claude" ? "Claude" : "Gemini"}${d.cached ? ", reused for this identical file" : ""}` : "local parser"})
      </h3>
      {d.fallback_reason && (
        <p className="fallback">
          {d.fallback_reason.startsWith("Skipped")
            ? "The AI reader was busy on an earlier invoice moments ago, so this one went straight to the local reader instead of waiting again."
            : `The AI reader could not be reached (${d.fallback_reason}), so the local reader was used instead.`}
        </p>
      )}
      {(d.progress?.length ?? 0) > 1 && (
        <>
          <h3>What the reader did</h3>
          <ol className="progress-log done">
            {d.progress.map((m: string, i: number) => <li key={i}>{m}</li>)}
          </ol>
        </>
      )}
      <table className="kv">
        <thead>
          <tr><th>Field</th><th>Value</th><th>Confidence</th></tr>
        </thead>
        <tbody>
          {order.map((k) => (
            <tr key={k} className={flagged.has(k) ? "flag" : ""}>
              <td>{fieldLabel(k)}</td>
              <td>
                {fmt(k, d.fields?.[k])}
                {d.evidence?.[k] && <div className="snippet">“{d.evidence[k]}”</div>}
              </td>
              <td><Conf v={d.confidence?.[k]} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {d.fields?.notes && (
        <>
          <h3>Note printed on the invoice</h3>
          <p style={{ margin: 0 }}>{d.fields.notes}</p>
        </>
      )}
      <h3>Line items</h3>
      <table className="kv">
        <thead>
          <tr><th>Description</th><th className="num">Qty</th><th className="num">Rate</th><th className="num">Amount</th></tr>
        </thead>
        <tbody>
          {(d.line_items ?? []).map((li: any, i: number) => (
            <tr key={i}>
              <td>{li.description}</td>
              <td className="num">{li.quantity ?? "—"} {li.uom ?? ""}</td>
              <td className="num">{inr(li.unit_price)}</td>
              <td className="num">{inr(li.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {(d.checks ?? []).filter((c: any) => c.check).length > 0 && (
        <>
          <h3>Cross-checks used to score confidence</h3>
          <ul className="rules">
            {d.checks.filter((c: any) => c.check).map((c: any, i: number) => (
              <li key={i} className={c.passed ? "pass" : "warn"}>
                <span className="mark" />
                <span>{c.check}: <span className="muted">{c.detail}</span></span>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function PoLines({ rows }: { rows: any[] }) {
  return (
    <table className="kv" style={{ marginTop: 6 }}>
      <thead>
        <tr><th>PO line</th><th className="num">Billed now</th><th className="num">Billed before</th>
          <th className="num">Ordered</th><th className="num">Rate vs PO</th></tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const over = r.qty + r.already_billed > r.po_qty;
          const priceOff = Math.abs(r.unit_price - r.po_unit_price) > 0.001;
          return (
            <tr key={i} className={over || priceOff ? "flag" : ""}>
              <td>{r.po_desc}</td>
              <td className="num">{r.qty}</td>
              <td className="num">{r.already_billed}</td>
              <td className="num">{r.po_qty}</td>
              <td className="num">{inr(r.unit_price)} / {inr(r.po_unit_price)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function RuleEvidence({ d, tech }: { d: any; tech?: boolean }) {
  const lineRule = (d.rules ?? []).find((r: any) => r.id === "R11" && r.evidence?.lines?.length);
  const cands = (d.rules ?? []).find((r: any) => r.id === "R9" && r.evidence?.candidates)?.evidence.candidates;
  return (
    <>
      <ul className="rules">
        {(d.rules ?? []).map((r: any) => (
          <li key={r.id} className={r.status}>
            <span className="mark" />
            <span>
              <span className="rn">{r.name}</span>
              {tech && <span className="muted"> ({r.id})</span>}
              <br />
              {r.reason}
            </span>
          </li>
        ))}
      </ul>
      {lineRule && (
        <>
          <h3>Invoice lines against the purchase order</h3>
          <PoLines rows={lineRule.evidence.lines} />
        </>
      )}
      {cands && (
        <>
          <h3>Purchase orders considered</h3>
          <table className="kv">
            <thead>
              <tr><th>PO</th><th className="num">PO value</th><th className="num">Amount fit</th>
                <th className="num">Item fit</th><th className="num">Score</th></tr>
            </thead>
            <tbody>
              {cands.map((c: any, i: number) => (
                <tr key={c.po_number} className={i === 0 ? "flag" : ""}>
                  <td>{c.po_number}</td>
                  <td className="num">{inr(c.po_subtotal)}</td>
                  <td className="num">{c.amount_similarity.toFixed(2)}</td>
                  <td className="num">{Math.max(c.item_similarity, c.keyword_overlap).toFixed(2)}</td>
                  <td className="num"><b>{c.score.toFixed(2)}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}

export default function Evidence({ stage, tech }: { stage: Stage; tech?: boolean }) {
  const d = stage.detail ?? {};
  switch (stage.key) {
    case "ingest":
      return (
        <table className="kv">
          <tbody>
            <tr><td>File</td><td>{d.file ?? "—"}</td></tr>
            <tr><td>Fingerprint (SHA-256)</td><td>{d.sha256 ?? "—"}</td></tr>
            {d.duplicate_of_run && <tr className="flag"><td>Same file as</td><td>run #{d.duplicate_of_run}</td></tr>}
          </tbody>
        </table>
      );
    case "classify":
      return (
        <table className="kv">
          <tbody>
            <tr><td>Route</td><td>{d.route === "scan" ? "Scanned image: vision / OCR" : "Digital text"}</td></tr>
            <tr><td>Readable characters per page</td><td>{(d.chars_per_page ?? []).join(", ")}</td></tr>
          </tbody>
        </table>
      );
    case "extract":
      return <ExtractEvidence d={d} />;
    case "decide":
      return (
        <table className="kv">
          <tbody>
            <tr><td>Decision</td><td><b>{d.decision}</b></td></tr>
            <tr><td>Overall confidence</td><td><Conf v={d.confidence} /></td></tr>
            <tr><td>Checks</td><td>
              {d.counts?.pass ?? 0} passed, {d.counts?.note ?? 0} noted, {d.counts?.warn ?? 0} held,{" "}
              {d.counts?.fail ?? 0} failed, {d.counts?.skip ?? 0} not applicable
            </td></tr>
            {(d.drivers ?? []).map((r: any) => (
              <tr key={r.id}><td>{r.name}</td><td>{r.reason}</td></tr>
            ))}
          </tbody>
        </table>
      );
    case "output":
      return (
        <table className="kv">
          <tbody>
            <tr><td>Next step</td><td>{d.next_action?.action}</td></tr>
            {d.next_action?.owner && <tr><td>Owner</td><td>{d.next_action.owner}</td></tr>}
            {d.next_action?.due_date && <tr><td>Payment due</td><td>{d.next_action.due_date}</td></tr>}
          </tbody>
        </table>
      );
    default:
      if (d.traceback) return <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{d.traceback}</pre>;
      return <RuleEvidence d={d} tech={tech} />;
  }
}
