import { useState } from "react";
import { api, timeAgo } from "./api";

const ACTION_WORD: Record<string, string> = {
  received: "Received", decided: "Decided by rules", approved: "Approved", rejected: "Rejected",
};

export function ReviewPanel({ runId, onDone }: { runId: number; onDone: (r: any) => void }) {
  const [note, setNote] = useState("");
  const [name, setName] = useState(() => {
    try { return localStorage.getItem("reviewer") || ""; } catch { return ""; }
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = (action: "approve" | "reject") => {
    if (!note.trim()) {
      setError("Add a short note saying what you checked.");
      return;
    }
    setBusy(action);
    setError(null);
    try { localStorage.setItem("reviewer", name); } catch {}
    api.review(runId, action, note, name.trim() || "AP reviewer")
      .then(onDone).catch((e) => setError(e.message)).finally(() => setBusy(null));
  };

  return (
    <div className="review">
      <h2>Your review</h2>
      <label htmlFor="rnote" className="sr-only">Note</label>
      <textarea id="rnote" rows={3} value={note} onChange={(e) => setNote(e.target.value)}
        placeholder="What did you check? For example: called the vendor on the number on file; new account confirmed." />
      <div className="review-row">
        <label htmlFor="rname" className="sr-only">Your name</label>
        <input id="rname" placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn approve" disabled={!!busy} onClick={() => act("approve")}>
          {busy === "approve" ? "Approving…" : "Approve invoice"}
        </button>
        <button className="btn reject" disabled={!!busy} onClick={() => act("reject")}>
          {busy === "reject" ? "Rejecting…" : "Reject invoice"}
        </button>
      </div>
      {error && <p className="field-error">{error}</p>}
    </div>
  );
}

export function AuditTrail({ events }: { events: any[] }) {
  if (!events?.length) return null;
  return (
    <div className="audit">
      <h2>Audit trail</h2>
      <ol>
        {events.map((e) => (
          <li key={e.id}>
            <span className="who">{ACTION_WORD[e.action] ?? e.action}</span>{" "}
            <span className="muted">by {e.actor}, {timeAgo(e.at)}</span>
            {e.detail && e.action !== "received" && <div className="what">{e.detail}</div>}
          </li>
        ))}
      </ol>
    </div>
  );
}
