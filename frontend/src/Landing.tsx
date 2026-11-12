import { useEffect, useState } from "react";
import { api, inr } from "./api";
import { SITE } from "./site";

const STEPS = [
  ["Receive file", "Fingerprint the PDF so an identical re-send is caught at once."],
  ["Check document type", "Text PDF or scanned image? That decides how it is read."],
  ["Read the invoice", "The AI model reads it into one fixed set of fields, each with a confidence score."],
  ["Validate fields and figures", "Required fields, arithmetic, GST rates and currency."],
  ["Check vendor and bank", "Approved vendor? Bank account the one on file?"],
  ["Look for duplicates", "Invoice numbers compared after normalising, plus amount and date."],
  ["Match to purchase order", "Line prices, quantities already billed, and the total against tolerance."],
  ["Decide", "The most serious finding wins: approve, approve with a note, hold or reject."],
  ["Record and route", "Name who acts next and draft the email to the vendor when one is needed."],
];

const CASES = [
  {
    file: "04_split_po_part2_over.pdf", title: "Split order that over-bills", decision: "On hold", tone: "hold",
    body: "60 of 100 boxes were billed last week. This invoice bills 55 more. Each looks fine alone; together they bill 15 too many.",
  },
  {
    file: "05_duplicate_renumbered.pdf", title: "Re-sent invoice, new number", decision: "Rejected", tone: "reject",
    body: "INV-0042 comes back as “INV 42” with a new date. Exact matching misses it; normalising the number doesn’t.",
  },
  {
    file: "06_scanned_no_po.pdf", title: "Scan with no order number", decision: "On hold", tone: "hold",
    body: "A photocopied invoice with bundled items. The likely order is found, a decoy from the same vendor ruled out, and a person confirms.",
  },
  {
    file: "07_bank_changed.pdf", title: "New bank account", decision: "On hold", tone: "hold",
    body: "Vendor, order, prices and totals all match. Only the bank account changed, and that alone stops payment.",
  },
];

export function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

/** Go to a section of the landing page from anywhere on the site. */
export function goSection(id: string) {
  const h = window.location.hash;
  if (h === "" || h === "#/" || h === "#") scrollTo(id);
  else {
    sessionStorage.setItem("scrollTo", id);
    window.location.hash = "#/";
  }
}

export default function Landing() {
  const [stats, setStats] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.stats().then(setStats).catch(() => {});
    const want = sessionStorage.getItem("scrollTo");
    if (want) {
      sessionStorage.removeItem("scrollTo");
      setTimeout(() => scrollTo(want), 50);
    }
  }, []);

  const runAll = () => {
    setBusy("all");
    setError(null);
    api.runAll().then(() => (window.location.hash = "#/history"))
      .catch((e) => setError(e.message)).finally(() => setBusy(null));
  };
  // Cases 4 and 5 only make sense after the earlier invoices, so every case starts a full ordered run
  // and opens the run for that invoice.
  const runOne = (file: string) => {
    setBusy(file);
    setError(null);
    const idx = parseInt(file, 10) - 1;
    api.runAll().then((r) => (window.location.hash = `#/runs/${r.run_ids[idx] ?? r.run_ids[0]}`))
      .catch((e) => setError(e.message)).finally(() => setBusy(null));
  };

  return (
    <div className="landing">
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-copy">
          <h1 id="hero-title">Every vendor invoice decided in seconds, with the reason written down.</h1>
          <p className="hero-sub">
            Upload an invoice. The AI model reads it, explicit rules check it against vendors, purchase orders and
            earlier invoices, and you get a decision a finance team can audit: approve, hold or reject, and who acts next.
          </p>
          {error && <div className="error-banner">{error}</div>}
          <div className="hero-cta">
            <button className="btn primary big" disabled={!!busy} onClick={runAll}>
              {busy === "all" ? "Starting…" : "Run the 8 sample invoices"}
            </button>
            <a className="btn big" href="#/run">Upload your own invoice</a>
          </div>
          <p className="hero-note">Runs live on this server, no sign-up. Running the samples clears earlier demo results first.</p>
        </div>

        <figure className="hero-art" aria-label="Example: an invoice held because its bank account changed">
          <div className="hero-sheet">
            <img src="/hero-invoice.png" alt="" />
            <span className="hero-hl" style={{ left: "12.4%", top: "64%", width: "18%", height: "5.8%" }} />
            <span className="stamp hold hero-stamp">On hold</span>
          </div>
          <figcaption className="hero-card">
            <b>Bank account changed</b>
            <span>On file …2295, this invoice …8890</span>
            <span className="muted">Treasury to confirm by phone before payment</span>
          </figcaption>
        </figure>
      </section>

      {stats && stats.invoices > 0 && (
        <dl className="proof" aria-label="On this server so far">
          <div><dt>Invoices processed here</dt><dd>{stats.invoices}</dd></div>
          <div><dt>Decided without a person</dt><dd>{stats.auto_decided_pct}%</dd></div>
          <div><dt>Waiting for review</dt><dd>{stats.waiting_review}</dd></div>
          <div><dt>Value checked (INR)</dt><dd>{inr(stats.value)}</dd></div>
        </dl>
      )}

      <section id="how" className="band" aria-labelledby="how-title">
        <h2 id="how-title">What happens to an invoice</h2>
        <p className="band-lede">Nine steps, always in the same order, each one recorded with what it compared.</p>
        <ol className="flow">
          {STEPS.map(([t, d], i) => (
            <li key={t}>
              <span className="flow-n">{i + 1}</span>
              <b>{t}</b>
              <span>{d}</span>
            </li>
          ))}
        </ol>
      </section>

      <section id="cases" className="band" aria-labelledby="cases-title">
        <h2 id="cases-title">Four invoices that trip up simple tools</h2>
        <p className="band-lede">Each is a sample you can run now and inspect step by step.</p>
        <div className="cases">
          {CASES.map((c) => (
            <article key={c.file} className="case">
              <header>
                <h3>{c.title}</h3>
                <span className={`badge ${c.tone}`}>{c.decision}</span>
              </header>
              <p>{c.body}</p>
              <button className="linkbtn" disabled={!!busy} onClick={() => runOne(c.file)}>
                {busy === c.file ? "Starting…" : "Watch it decide"}
              </button>
            </article>
          ))}
        </div>
        <p className="band-foot">
          Cases 4 and 5 depend on invoices that came before them, as in real life, so each one runs all eight samples
          in order and opens the one you picked.
        </p>
      </section>

      <section id="principle" className="band split" aria-labelledby="principle-title">
        <div>
          <h2 id="principle-title">The AI model reads. The rules decide.</h2>
          <p>
            Reading messy documents is where a model beats templates. Deciding whether to pay is where a finance team
            needs rules it can read, test and change. So the model only turns the PDF into fields, and twelve plain
            rules make the call.
          </p>
        </div>
        <ul className="pillars">
          <li>
            <b>Reading that knows its limits</b>
            <span>Every field carries a confidence score, checked against the invoice’s own arithmetic. If the AI is
              unavailable, a local reader takes over and says so.</span>
          </li>
          <li>
            <b>Rules you can change live</b>
            <span>Price tolerance, duplicate windows and the confidence bar are settings, not code.</span>
          </li>
          <li>
            <b>People decide the hard ones</b>
            <span>Held invoices go to a review queue. Approving one needs a note, and the audit trail keeps both the
              rules’ decision and the person’s.</span>
          </li>
        </ul>
      </section>

      <Contact />
    </div>
  );
}

export function Contact() {
  const { email, linkedin, github } = SITE.contact;
  const [name, setName] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const send = (e: React.FormEvent) => {
    e.preventDefault();
    if (!msg.trim()) {
      setErr("Write a short message first.");
      return;
    }
    setErr(null);
    const subject = encodeURIComponent(`Invoice Agent: message from ${name.trim() || "a visitor"}`);
    window.location.href = `mailto:${email}?subject=${subject}&body=${encodeURIComponent(msg.trim())}`;
  };
  return (
    <section id="contact" className="band contact" aria-labelledby="contact-title">
      <div>
        <h2 id="contact-title">Contact</h2>
        <p>
          Questions about how the process decides, or want to see it run on your own invoices?
          {SITE.author && <> Get in touch with {SITE.author}.</>}
        </p>
        {(linkedin || github || email) && (
          <ul className="contact-links">
            {email && <li><a href={`mailto:${email}`}>{email}</a></li>}
            {linkedin && <li><a href={linkedin} target="_blank" rel="noreferrer">LinkedIn</a></li>}
            {github && <li><a href={github} target="_blank" rel="noreferrer">GitHub</a></li>}
          </ul>
        )}
      </div>
      {email ? (
        <form className="contact-form" onSubmit={send}>
          <label>
            <span>Your name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
          </label>
          <label>
            <span>Message</span>
            <textarea rows={4} value={msg} onChange={(e) => setMsg(e.target.value)} />
          </label>
          {err && <p className="field-error">{err}</p>}
          <button className="btn primary" type="submit">Open in your email app</button>
        </form>
      ) : import.meta.env.DEV ? (
        <p className="muted contact-empty">Add an email in <code>frontend/src/site.ts</code> to show the contact form.</p>
      ) : null}
    </section>
  );
}
