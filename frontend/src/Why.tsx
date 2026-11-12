import { fieldLabel, inr, money, Stage } from "./api";

type Fact = { label: string; value: string; flag?: boolean };

function tail(acct?: string | null) {
  if (!acct) return "none";
  return acct.startsWith("…") ? acct : "…" + acct.slice(-4);
}

/** The few numbers behind the decision, taken from the evidence of the rule that drove it. */
function factsFor(rule: any, fields: any): { caption?: string; facts: Fact[] } {
  const ev = rule?.evidence ?? {};
  switch (rule?.id) {
    case "R11": {
      const ln = (ev.lines ?? []).find((l: any) => l.qty + l.already_billed > l.po_qty) ?? ev.lines?.[0];
      if (!ln) return { facts: [] };
      const over = ln.qty + ln.already_billed - ln.po_qty;
      return {
        caption: ln.po_desc,
        facts: [
          { label: "Ordered on the PO", value: String(ln.po_qty) },
          { label: "Billed before", value: String(ln.already_billed) },
          { label: "This invoice", value: String(ln.qty) },
          { label: "Over the PO by", value: String(over), flag: true },
        ],
      };
    }
    case "R10": {
      const ln = (ev.lines ?? []).find((l: any) => Math.abs(l.unit_price - l.po_unit_price) > 0.001);
      if (!ln) return { facts: [] };
      const pct = ((ln.unit_price - ln.po_unit_price) / ln.po_unit_price) * 100;
      return {
        caption: ln.po_desc,
        facts: [
          { label: "PO price", value: inr(ln.po_unit_price) },
          { label: "Invoice price", value: inr(ln.unit_price) },
          { label: "Difference", value: `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`, flag: true },
        ],
      };
    }
    case "R6":
      return {
        facts: [
          { label: "Account on file", value: `${tail(ev.master_account)} · ${ev.master_ifsc ?? ""}` },
          { label: "Account on this invoice", value: `${tail(ev.invoice_account)} · ${ev.invoice_ifsc ?? ""}`, flag: true },
        ],
      };
    case "R7":
      if (!ev.prior_number) return { facts: [{ label: "Same file as", value: `Run #${ev.duplicate_of_run}`, flag: true }] };
      return {
        facts: [
          { label: `Earlier invoice (run #${ev.duplicate_of_run})`, value: ev.prior_number },
          { label: "This invoice", value: fields.invoice_number ?? "—", flag: true },
          { label: "Both reduce to", value: ev.normalised },
        ],
      };
    case "R8":
      return {
        facts: [
          { label: "Similar invoice", value: `Run #${ev.candidate_run}` },
          { label: "Amount difference", value: `${ev.amount_diff_pct}%`, flag: true },
          ...(ev.days_apart != null ? [{ label: "Days apart", value: String(ev.days_apart) }] : []),
        ],
      };
    case "R9": {
      const c = ev.candidates ?? [];
      if (!c.length) return { facts: [{ label: "PO cited", value: ev.cited ?? "none", flag: true }] };
      return {
        caption: "Fit of this vendor's open purchase orders, from 0 to 1",
        facts: c.slice(0, 3).map((x: any, i: number) => ({
          label: i === 0 ? `${x.po_number} (best match)` : x.po_number, value: x.score.toFixed(2), flag: i === 0,
        })),
      };
    }
    case "R12":
      return {
        caption: ev.extra_lines?.length ? `Not on the PO: ${ev.extra_lines.join(", ")}` : undefined,
        facts: [
          { label: "PO value for what was billed", value: inr(ev.expected_total) },
          { label: "Invoice total", value: inr(ev.invoice_total) },
          { label: "Difference", value: inr(ev.difference), flag: Math.abs(ev.difference ?? 0) > 1 },
          { label: "Allowed", value: inr(ev.allowed) },
        ],
      };
    case "R1":
      return {
        facts: (ev.missing ?? ev.unreadable ?? []).map((f: string) => ({
          label: ev.missing ? "Missing" : "Could not be read", value: fieldLabel(f), flag: true,
        })),
      };
    case "R2":
      return {
        caption: `Fields read below the ${ev.floor} confidence needed`,
        facts: Object.entries(ev.low_confidence ?? {}).map(([k, v]) => ({
          label: fieldLabel(k), value: Number(v).toFixed(2), flag: true,
        })),
      };
    case "R5":
      return {
        facts: [
          { label: "Name on the invoice", value: ev.read_name ?? ev.legal_name ?? "—", flag: true },
          ...(ev.read_gstin ? [{ label: "GSTIN on the invoice", value: ev.read_gstin }] : []),
        ],
      };
    case "R0":
      return {
        caption: "Fields missing here may well be on the invoice: check the original.",
        facts: [
          { label: "Key fields read", value: `${ev.found} of ${ev.of}`, flag: true },
          { label: "Invoice total read", value: fields.total != null ? money(fields.total, fields.currency) : "no" },
          { label: "Vendor read as", value: fields.vendor_name ?? "nothing" },
        ],
      };
    case "R4b":
      return {
        facts: [
          { label: "Invoice currency", value: ev.currency, flag: true },
          { label: "This process handles", value: "INR" },
        ],
      };
    default:
      return { facts: [] };
  }
}

export default function Why({ decision, stages, tech }: { decision: any; stages: Stage[]; tech: boolean }) {
  const rules: Record<string, any> = {};
  for (const s of stages) for (const r of s.detail?.rules ?? []) rules[r.id] = r;
  const fields = stages.find((s) => s.key === "extract")?.detail?.fields ?? {};
  const drivers: any[] = decision?.drivers ?? [];
  // Approved outright: show the comparison that passed, so "approved" is as checkable as "held".
  const lead = drivers.length ? rules[drivers[0].id] : rules["R12"];
  if (!lead) return null;
  const { caption, facts } = factsFor(lead, fields);
  if (!facts.length && drivers.length <= 1) return null;
  return (
    <div className="whybox">
      {facts.length > 0 && (
        <>
          <p className="why-title">
            {drivers.length ? "The numbers behind this" : "What was compared"}
            {tech && <span className="muted"> ({lead.id} {lead.name})</span>}
          </p>
          <dl className="facts-grid">
            {facts.map((f, i) => (
              <div key={i} className={f.flag ? "flag" : ""}>
                <dt>{f.label}</dt>
                <dd>{f.value}</dd>
              </div>
            ))}
          </dl>
          {caption && <p className="why-caption">{caption}</p>}
        </>
      )}
      {drivers.length > 1 && (
        <>
          <p className="why-title">Also found</p>
          <ul className="also">
            {drivers.slice(1).map((d) => (
              <li key={d.id}>{d.reason}{tech && <span className="muted"> ({d.id})</span>}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
