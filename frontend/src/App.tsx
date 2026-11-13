import { useEffect, useState } from "react";
import { api } from "./api";
import Dashboard from "./Dashboard";
import Home from "./Home";
import Settings from "./Settings";
import RunView from "./RunView";
import Landing, { goSection } from "./Landing";
import Footer from "./Footer";
import Master from "./Master";
import { SITE } from "./site";

function useHash() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const on = () => {
      setHash(window.location.hash || "#/");
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

export default function App() {
  const hash = useHash();
  const [mode, setMode] = useState<string | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    api.health().then((h) => { setMode(h.extractor); setProvider(h.provider); }).catch(() => setMode("offline"));
  }, []);
  useEffect(() => setOpen(false), [hash]);

  const runMatch = hash.match(/^#\/runs\/(\d+)/);
  const isLanding = !runMatch && !["#/run", "#/history", "#/settings", "#/master"].includes(hash);
  const cur = (on: boolean) => (on ? "page" : undefined);

  return (
    <>
      <header className={`topbar ${open ? "open" : ""}`}>
        <a className="brand" href="#/">
          <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
            <rect x="3.5" y="1.5" width="15" height="19" rx="2" fill="none" stroke="currentColor" strokeWidth="1.6" />
            <path d="M7 7h8M7 10.5h8M7 14h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            <path d="M12.5 15.5l1.8 1.8 3.4-3.6" stroke="var(--approve)" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <b>{SITE.product}</b>
        </a>
        <button className="menu-btn" aria-expanded={open} aria-controls="mainnav" onClick={() => setOpen((o) => !o)}>
          <span className="sr-only">Menu</span>
          <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
            {open ? <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              : <path d="M3 6h14M3 10h14M3 14h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />}
          </svg>
        </button>
        <nav className="nav" id="mainnav" aria-label="Main">
          <a href="#/" aria-current={cur(isLanding)}>Home</a>
          <a href="#/run" aria-current={cur(hash === "#/run")}>Try it</a>
          <a href="#/history" aria-current={cur(hash === "#/history" || !!runMatch)}>History</a>
          <a href="#/master" aria-current={cur(hash === "#/master")}>Vendors &amp; POs</a>
          <a href="#/settings" aria-current={cur(hash === "#/settings")}>Rule settings</a>
          <a href="#contact" onClick={(e) => { e.preventDefault(); setOpen(false); goSection("contact"); }}>Contact</a>
        </nav>
        {mode && (
          <span className="mode" title="How invoices are being read right now">
            <span className={`dot ${mode === "llm" ? "" : "local"}`} />
            {mode === "llm" ? `Reading with ${provider === "claude" ? "Claude" : "Gemini"}` : mode === "local" ? "Reading locally (OCR)" : "Server offline"}
          </span>
        )}
      </header>
      <main className={isLanding ? "is-landing" : ""}>
        {runMatch ? <RunView id={Number(runMatch[1])} /> : hash === "#/history" ? <Dashboard />
          : hash === "#/settings" ? <Settings /> : hash === "#/master" ? <Master /> : hash === "#/run" ? <Home /> : <Landing />}
      </main>
      <Footer />
    </>
  );
}
