import { useEffect, useMemo, useState } from "react";
import { call } from "../api.js";
import { Badge, Button, Callout, Empty, Icon, PageHeader } from "../ui.jsx";

// The audit log (SPEC section 2, story 5): who did what, when, with which model and prompt
// version. Append-only and hash-chained in Postgres (`just audit-verify`); admins and operators read it.
function tone(action) {
  if (action.startsWith("fhir.write") || action.endsWith("approve") || action === "lab.confirm") return "ok";
  if (action.startsWith("phi.") || action.startsWith("gdpr.")) return "warn";
  if (action.includes("refuse") || action.endsWith("reject")) return "danger";
  if (action.startsWith("draft.") || action === "ask") return "ai";
  return "neutral";
}

function when(ts) {
  const date = new Date(ts?.replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return { short: ts, full: ts };
  const minutes = Math.round((Date.now() - date.getTime()) / 60000);
  const short =
    minutes < 1 ? "just now" : minutes < 60 ? `${minutes} min ago` : minutes < 1440 ? `${Math.round(minutes / 60)} h ago` : date.toLocaleDateString();
  return { short, full: date.toLocaleString() };
}

export default function Audit() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [action, setAction] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true);
    setError("");
    try {
      setRows(await call("GET", "/v1/audit?limit=200"));
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  }
  useEffect(() => {
    load();
  }, []);

  const actions = useMemo(() => [...new Set((rows ?? []).map((r) => r.action))].sort(), [rows]);
  const shown = (rows ?? []).filter((r) => {
    if (action && r.action !== action) return false;
    if (!query) return true;
    const hay = [r.actor, r.role, r.action, r.resource_type, r.resource_id, r.model, r.prompt_version].join(" ").toLowerCase();
    return hay.includes(query.toLowerCase());
  });

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Every read, draft, disclosure and write, with the model and prompt version that produced it. Append-only and hash-chained: no row can be changed or removed unnoticed."
      >
        <Button variant="secondary" icon="refresh" busy={busy} onClick={load}>
          Refresh
        </Button>
      </PageHeader>
      <div className="card">
        <div className="card-head">
          <div className="row grow">
            <input
              type="search"
              placeholder="Search actor, action, resource, model…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ minWidth: 260 }}
              aria-label="Search the audit log"
            />
            <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action">
              <option value="">All actions</option>
              {actions.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </div>
          <span className="muted small">
            {rows ? `${shown.length} of ${rows.length} rows` : "loading"}
          </span>
        </div>
        {error && <div className="card-body"><Callout tone="danger">{error}</Callout></div>}
        {rows && shown.length === 0 && <Empty icon="audit" title="No matching rows" />}
        {rows === null && !error && (
          <div className="card-body stack">
            {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 30 }} />)}
          </div>
        )}
        {shown.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>When</th>
                  <th>Who</th>
                  <th>Action</th>
                  <th>Resource</th>
                  <th>Model · prompt</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => {
                  const t = when(r.ts);
                  return (
                    <tr key={r.seq}>
                      <td className="mono muted small">{r.seq}</td>
                      <td title={t.full} className="small" style={{ whiteSpace: "nowrap" }}>{t.short}</td>
                      <td>
                        <div className="row" style={{ flexWrap: "nowrap", gap: 8 }}>
                          <span className="avatar" style={{ width: 26, height: 26, fontSize: "0.68rem" }}>
                            {(r.actor ?? "?").split("-").map((part) => part[0]).join("").slice(0, 2).toUpperCase()}
                          </span>
                          <div>
                            <div className="small" style={{ fontWeight: 600 }}>{r.actor}</div>
                            <div className="muted small">{r.role}</div>
                          </div>
                        </div>
                      </td>
                      <td><Badge tone={tone(r.action)}>{r.action}</Badge></td>
                      <td className="small">
                        {r.resource_type && <span className="muted">{r.resource_type} </span>}
                        <span className="mono">{r.resource_id ?? ""}</span>
                      </td>
                      <td className="mono small muted" style={{ whiteSpace: "nowrap" }}>
                        {r.model && r.model !== "none" ? <div>{r.model}</div> : null}
                        {r.prompt_version && r.prompt_version !== "none" ? <div>{r.prompt_version}</div> : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <p className="muted small row" style={{ marginTop: 12 }}>
        <Icon name="shield" size={14} /> Rows carry ids and counts, never clinical text. Each row is chained to the one before
        with an HMAC; <code>just audit-verify</code> names the first broken row.
      </p>
    </>
  );
}
