import { useEffect, useState } from "react";
import { api } from "./api";
import Dashboard from "./Dashboard";
import Home from "./Home";
import Settings from "./Settings";
import RunView from "./RunView";

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
  useEffect(() => {
    api.health().then((h) => { setMode(h.extractor); setProvider(h.provider); }).catch(() => setMode("offline"));
  }, []);

  const runMatch = hash.match(/^#\/runs\/(\d+)/);
  return (
    <>
      <header className="topbar">
        <a className="brand" href="#/">
          <b>Kestrel Components</b>
          <span>Accounts payable</span>
        </a>
        <nav className="nav" aria-label="Main">
          <a href="#/" aria-current={hash === "#/" ? "page" : undefined}>Run an invoice</a>
          <a href="#/history" aria-current={hash === "#/history" || runMatch ? "page" : undefined}>History</a>
          <a href="#/settings" aria-current={hash === "#/settings" ? "page" : undefined}>Rule settings</a>
        </nav>
        {mode && (
          <span className="mode">
            <span className={`dot ${mode === "llm" ? "" : "local"}`} />
            {mode === "llm" ? `Reading with ${provider === "claude" ? "Claude" : "Gemini"}` : mode === "local" ? "Reading locally (OCR fallback)" : "Server offline"}
          </span>
        )}
      </header>
      <main>
        {runMatch ? <RunView id={Number(runMatch[1])} /> : hash === "#/history" ? <Dashboard />
          : hash === "#/settings" ? <Settings /> : <Home />}
      </main>
    </>
  );
}
