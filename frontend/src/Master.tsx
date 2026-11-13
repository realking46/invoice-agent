import { Fragment, useEffect, useState } from "react";
import { api, inr } from "./api";

const blankVendor = { legal_name: "", gstin: "", address: "", bank_account: "", ifsc: "", payment_terms_days: "30" };
const blankLine = () => ({ description: "", qty: "", uom: "Nos", unit_price: "", tax_rate: "18" });

export default function Master() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [vOpen, setVOpen] = useState(false);
  const [pOpen, setPOpen] = useState(false);
  const [v, setV] = useState<Record<string, string>>(blankVendor);
  const [vErr, setVErr] = useState<string | null>(null);
  const [po, setPo] = useState<{ vendor_id: string; po_number: string; lines: Record<string, string>[] }>(
    { vendor_id: "", po_number: "", lines: [blankLine()] });
  const [pErr, setPErr] = useState<string | null>(null);
  const [openPo, setOpenPo] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const load = () => api.master().then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  const done = (msg: string) => { setFlash(msg); setTimeout(() => setFlash(null), 4000); load(); };

  const saveVendor = (e: React.FormEvent) => {
    e.preventDefault();
    setVErr(null);
    api.addVendor({ ...v, payment_terms_days: Number(v.payment_terms_days || 30) })
      .then((r) => { setV(blankVendor); setVOpen(false); done(`${r.legal_name} added as ${r.vendor_id}.`); })
      .catch((e) => setVErr(e.message));
  };

  const savePo = (e: React.FormEvent) => {
    e.preventDefault();
    setPErr(null);
    if (!po.vendor_id) return setPErr("Pick a vendor.");
    const lines = po.lines.filter((l) => l.description.trim());
    if (!lines.length) return setPErr("Add at least one line with a description.");
    if (lines.some((l) => !(Number(l.qty) > 0) || !(Number(l.unit_price) >= 0) || l.unit_price === ""))
      return setPErr("Every line needs a quantity above zero and a unit price.");
    api.addPO({
      vendor_id: po.vendor_id, po_number: po.po_number,
      lines: lines.map((l) => ({ description: l.description, qty: Number(l.qty), uom: l.uom || "Nos",
        unit_price: Number(l.unit_price), tax_rate: Number(l.tax_rate || 18) })),
    }).then((r) => {
      setPo({ vendor_id: "", po_number: "", lines: [blankLine()] });
      setPOpen(false);
      done(`${r.po_number} created for ${inr(r.total)} including tax.`);
    }).catch((e) => setPErr(e.message));
  };

  const setLine = (i: number, k: string, val: string) =>
    setPo({ ...po, lines: po.lines.map((l, j) => (j === i ? { ...l, [k]: val } : l)) });

  if (error) return <div className="error-banner">{error}</div>;
  if (!data) return <p className="muted">Loading vendors and purchase orders…</p>;

  return (
    <div className="master">
      <div className="pagehead">
        <div>
          <h1>Vendors and purchase orders</h1>
          <p className="lede">
            The procurement data every invoice is checked against. Add a vendor and an order here, then upload that
            vendor's invoice to see it matched. Reset demo data restores the original list.
          </p>
        </div>
      </div>
      {flash && <div className="flash" role="status">{flash}</div>}

      <section className="panel" aria-labelledby="vh">
        <div className="panel-head">
          <h2 id="vh">Vendors <span className="count-muted">{data.vendors.length}</span></h2>
          <button className="btn" onClick={() => setVOpen((o) => !o)} aria-expanded={vOpen}>
            {vOpen ? "Cancel" : "Add a vendor"}
          </button>
        </div>
        {vOpen && (
          <form className="mform" onSubmit={saveVendor}>
            <label><span>Legal name</span><input required value={v.legal_name} onChange={(e) => setV({ ...v, legal_name: e.target.value })} /></label>
            <label><span>GSTIN</span><input required placeholder="27AAKFS1234L1ZZ" value={v.gstin} onChange={(e) => setV({ ...v, gstin: e.target.value })} /></label>
            <label className="wide"><span>Address</span><input value={v.address} onChange={(e) => setV({ ...v, address: e.target.value })} /></label>
            <label><span>Bank account number</span><input required inputMode="numeric" value={v.bank_account} onChange={(e) => setV({ ...v, bank_account: e.target.value })} /></label>
            <label><span>IFSC</span><input required placeholder="HDFC0001234" value={v.ifsc} onChange={(e) => setV({ ...v, ifsc: e.target.value })} /></label>
            <label><span>Payment terms (days)</span><input type="number" min={0} value={v.payment_terms_days} onChange={(e) => setV({ ...v, payment_terms_days: e.target.value })} /></label>
            <div className="mform-actions wide">
              {vErr && <p className="field-error">{vErr}</p>}
              <button className="btn primary" type="submit">Save vendor</button>
            </div>
          </form>
        )}
        <div className="tablewrap flat">
          <table className="vendors">
            <thead><tr><th>ID</th><th>Vendor</th><th>GSTIN</th><th>Bank account</th><th>Terms</th><th>Status</th></tr></thead>
            <tbody>
              {data.vendors.map((x: any) => (
                <tr key={x.vendor_id}>
                  <td className="muted">{x.vendor_id}</td>
                  <td><b>{x.legal_name}</b>{x.address && <div className="muted small">{x.address}</div>}</td>
                  <td>{x.gstin}</td>
                  <td>…{x.bank_account.slice(-4)} · {x.ifsc}</td>
                  <td>{x.payment_terms_days} days</td>
                  <td><span className={`badge ${x.status === "approved" ? "approve" : "reject"}`}>
                    {x.status === "approved" ? "Approved" : "Blocked"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel" aria-labelledby="ph">
        <div className="panel-head">
          <h2 id="ph">Purchase orders <span className="count-muted">{data.purchase_orders.length}</span></h2>
          <button className="btn" onClick={() => setPOpen((o) => !o)} aria-expanded={pOpen}>
            {pOpen ? "Cancel" : "Add a purchase order"}
          </button>
        </div>
        {pOpen && (
          <form className="mform" onSubmit={savePo}>
            <label><span>Vendor</span>
              <select value={po.vendor_id} onChange={(e) => setPo({ ...po, vendor_id: e.target.value })}>
                <option value="">Choose a vendor</option>
                {data.vendors.filter((x: any) => x.status === "approved").map((x: any) =>
                  <option key={x.vendor_id} value={x.vendor_id}>{x.legal_name}</option>)}
              </select>
            </label>
            <label><span>PO number (optional)</span>
              <input placeholder="Next free number" value={po.po_number} onChange={(e) => setPo({ ...po, po_number: e.target.value })} />
            </label>
            <div className="wide">
              <table className="lines-edit">
                <thead><tr><th>Item</th><th>Qty</th><th>Unit</th><th>Unit price (₹)</th><th>GST %</th><th></th></tr></thead>
                <tbody>
                  {po.lines.map((l, i) => (
                    <tr key={i}>
                      <td><input aria-label={`Line ${i + 1} item`} value={l.description} onChange={(e) => setLine(i, "description", e.target.value)} /></td>
                      <td><input aria-label={`Line ${i + 1} quantity`} type="number" min={0} step="any" value={l.qty} onChange={(e) => setLine(i, "qty", e.target.value)} /></td>
                      <td><input aria-label={`Line ${i + 1} unit`} value={l.uom} onChange={(e) => setLine(i, "uom", e.target.value)} /></td>
                      <td><input aria-label={`Line ${i + 1} unit price`} type="number" min={0} step="any" value={l.unit_price} onChange={(e) => setLine(i, "unit_price", e.target.value)} /></td>
                      <td><input aria-label={`Line ${i + 1} GST rate`} type="number" min={0} step="any" value={l.tax_rate} onChange={(e) => setLine(i, "tax_rate", e.target.value)} /></td>
                      <td>{po.lines.length > 1 && (
                        <button type="button" className="linkbtn" onClick={() => setPo({ ...po, lines: po.lines.filter((_, j) => j !== i) })}>Remove</button>
                      )}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button type="button" className="linkbtn" onClick={() => setPo({ ...po, lines: [...po.lines, blankLine()] })}>Add a line</button>
            </div>
            <div className="mform-actions wide">
              {pErr && <p className="field-error">{pErr}</p>}
              <button className="btn primary" type="submit">Create purchase order</button>
            </div>
          </form>
        )}
        <div className="tablewrap flat">
          <table className="vendors">
            <thead><tr><th>PO</th><th>Vendor</th><th>Date</th><th className="num">Total</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {data.purchase_orders.map((p: any) => (
                <Fragment key={p.po_number}>
                  <tr>
                    <td><b>{p.po_number}</b></td>
                    <td>{p.vendor_name}</td>
                    <td>{p.po_date}</td>
                    <td className="num">{inr(p.total_amount)}</td>
                    <td><span className={`badge ${p.status === "open" ? "note" : "pending"}`}>{p.status === "open" ? "Open" : "Closed"}</span></td>
                    <td><button className="linkbtn" aria-expanded={openPo === p.po_number}
                      onClick={() => setOpenPo(openPo === p.po_number ? null : p.po_number)}>
                      {openPo === p.po_number ? "Hide lines" : `${p.lines.length} line${p.lines.length === 1 ? "" : "s"}`}</button></td>
                  </tr>
                  {openPo === p.po_number && (
                    <tr className="po-lines">
                      <td colSpan={6}>
                        <table>
                          <tbody>
                            {p.lines.map((l: any) => (
                              <tr key={l.line_no}>
                                <td className="muted">{l.line_no}</td><td>{l.description}</td>
                                <td className="num">{l.qty} {l.uom}</td><td className="num">{inr(l.unit_price)}</td>
                                <td className="muted">GST {l.tax_rate}%</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
