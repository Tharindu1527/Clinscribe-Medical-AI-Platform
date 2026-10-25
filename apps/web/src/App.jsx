import { useState } from "react";
import { call, setToken } from "./api.js";

const SECTIONS = ["subjective", "objective", "assessment", "plan"];
const SAMPLE = `D: Good morning, what brings you in today?
P: I have been really thirsty and tired for about three weeks.
D: Your fasting glucose this morning was 9.1 mmol/L.
D: This fits type 2 diabetes; I would like to confirm with an HbA1c.
D: Let's start metformin 500 mg once daily with the evening meal.
D: We will review you in four weeks with the HbA1c result.`;

function Login({ onLogin }) {
  const [user, setUser] = useState("dr-demo");
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault();
    try {
      const { token, role } = await call("POST", "/v1/dev/login", { user });
      setToken(token);
      onLogin({ user, role });
    } catch (e) {
      setError(`${e.message}. Set DEV_LOGIN=true in .env and restart the API (just up).`);
    }
  }
  return (
    <form className="card narrow" onSubmit={submit}>
      <h2>Sign in (synthetic demo users)</h2>
      <select value={user} onChange={(e) => setUser(e.target.value)}>
        <option value="dr-demo">dr-demo (doctor)</option>
        <option value="dr-second">dr-second (doctor)</option>
        <option value="admin-demo">admin-demo (admin)</option>
        <option value="ops-demo">ops-demo (operator)</option>
      </select>
      <button type="submit">Sign in</button>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

function Citations({ ids, evidence }) {
  return ids.map((id) => {
    const source = evidence.find((e) => e.chunk_id === id);
    const n = evidence.indexOf(source) + 1;
    return (
      <a key={id} className="chip" href={source?.source_url} target="_blank" rel="noreferrer"
         title={source ? `${source.title} — ${source.section}` : id}>
        [{n || "?"}]
      </a>
    );
  });
}

function Ask() {
  const [question, setQuestion] = useState("Does clarithromycin interact with warfarin?");
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function ask(event) {
    event.preventDefault();
    setBusy(true); setError(""); setOut(null);
    try {
      setOut(await call("POST", "/v1/ask?identified=true",
        { encounter_id: `ask-${Date.now()}`, question }));
    } catch (e) { setError(e.message); }
    setBusy(false);
  }
  return (
    <section>
      <form className="card" onSubmit={ask}>
        <label>Question
          <textarea rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} />
        </label>
        <button disabled={busy}>{busy ? "Searching guidelines…" : "Ask"}</button>
      </form>
      {error && <p className="error">{error}</p>}
      {out && (
        <div className="card">
          <p className="label">AI-generated · {out.route} path · cite-or-abstain</p>
          {out.answer.abstained ? (
            <p className="abstain">
              {out.unseen_terms?.length
                ? `No source mentions ${out.unseen_terms.join(", ")}, so there is no answer with evidence.`
                : "No answer with evidence. Review the sources directly."}
            </p>
          ) : (
            out.answer.sentences.map((s, i) => (
              <p key={i}>{out.identified?.sentences[i] ?? s.text}{" "}
                <Citations ids={s.citations} evidence={out.evidence} /></p>
            ))
          )}
          {out.violations.length > 0 && (
            <p className="warn">Guardrails: {out.violations.join("; ")}</p>
          )}
          <h3>Sources</h3>
          <ol className="sources">
            {out.evidence.map((e) => (
              <li key={e.chunk_id}>
                <a href={e.source_url} target="_blank" rel="noreferrer">{e.title}</a> — {e.section}
                <details><summary>passage</summary><p>{e.text}</p></details>
              </li>
            ))}
          </ol>
          {out.dropped.length > 0 && <p className="warn">Dropped (injection): {out.dropped.join("; ")}</p>}
        </div>
      )}
    </section>
  );
}

// The doctor reads and edits the originals (re-identified by the API, audited; ADR-0015);
// "what the AI saw" shows the surrogate text the models worked on.
function Draft({ draft, onDone }) {
  const shown = draft.identified
    ? draft.draft.statements.map((s, i) => ({ ...s, text: draft.identified.statements[i] }))
    : draft.draft.statements;
  const transcript = draft.identified?.transcript ?? draft.transcript;
  const [statements, setStatements] = useState(shown);
  const [modelView, setModelView] = useState(false);
  const [birthDate, setBirthDate] = useState("");
  const [family, setFamily] = useState("");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [refused, setRefused] = useState(draft.refused ? `${draft.refused}.` : "");
  const edited = JSON.stringify(statements) !== JSON.stringify(shown);
  const unsupportedText = new Set(draft.unsupported.map((s) => s.text));
  const unsupported = new Set(
    draft.draft.statements.flatMap((s, i) => (unsupportedText.has(s.text) ? [i] : [])));

  async function decide(decision) {
    setError("");
    const body = { decision, birth_date: birthDate || null, family_name: family || null };
    if (decision === "edit") {
      body.edited = { ...draft.draft, statements };
      body.edited_identified = !!draft.identified;
    }
    if (decision === "reject") body.reason = reason || "rejected by the doctor";
    try {
      const out = await call("POST", `/v1/drafts/${draft.draft_id}/review`, body);
      if (out.awaiting_review) {  // wrong identifiers: refused and audited, the draft stays open
        setRefused(`${out.result.reason}. Check the identifiers and try again `
          + `(${out.attempts_left} attempt${out.attempts_left === 1 ? "" : "s"} left).`);
        return;
      }
      setRefused("");
      setResult(out.result);
      onDone?.();
    } catch (e) { setError(e.message); }
  }

  return (
    <div className="card">
      <p className="label">AI-generated draft · {draft.draft.prompt_version} · {draft.draft.model}</p>
      {draft.identified && (
        <label className="toggle">
          <input type="checkbox" checked={modelView} onChange={(e) => setModelView(e.target.checked)} />
          Show what the AI saw (names, dates and places as surrogates)
        </label>
      )}
      {SECTIONS.map((section) => (
        <div key={section}>
          <h3>{section}</h3>
          {statements.map((s, i) => s.section === section && (
            <div key={i} className={`statement ${unsupported.has(i) ? "unsupported" : ""}`}>
              <input value={modelView ? draft.draft.statements[i].text : s.text}
                     disabled={!!result || modelView}
                     onChange={(e) => setStatements(statements.map((x, j) =>
                       j === i ? { ...x, text: e.target.value } : x))} />
              <span className="turns" title={s.transcript_turns.map((t) =>
                (modelView ? draft.transcript : transcript)[t]).join("\n")}>
                turns {s.transcript_turns.join(", ")}
              </span>
              {unsupported.has(i) && <span className="tag">no guideline source</span>}
            </div>
          ))}
        </div>
      ))}
      {draft.removed.length > 0 && (
        <details className="warn"><summary>{draft.removed.length} statement(s) removed by guardrails</summary>
          <ul>{draft.removed.map((r, i) => <li key={i}>{r}</li>)}</ul></details>
      )}
      {!result && (
        <div className="review">
          <p>Confirm the patient (two identifiers) to approve:</p>
          {refused && <p className="warn">{refused}</p>}
          <input placeholder="birth date YYYY-MM-DD" value={birthDate} onChange={(e) => setBirthDate(e.target.value)} />
          <input placeholder="family name" value={family} onChange={(e) => setFamily(e.target.value)} />
          <div className="buttons">
            <button onClick={() => decide(edited ? "edit" : "approve")}>
              {edited ? "Approve with my edits" : "Approve"}
            </button>
            <input placeholder="reason to reject" value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="secondary" onClick={() => decide("reject")}>Reject</button>
          </div>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {result && (
        <p className={result.status === "written" ? "ok" : "warn"}>
          {result.status === "written"
            ? `Saved to FHIR: ${result.resource_type}/${result.resource_id}`
            : `${result.status}: ${result.reason ?? ""}`}
        </p>
      )}
    </div>
  );
}

// Drafts made elsewhere, e.g. by the Scribe audio listener (`just scribe <patient id>`)
function Waiting({ onOpen }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  async function load() {
    setError("");
    try { setRows(await call("GET", "/v1/drafts")); } catch (e) { setError(e.message); }
  }
  return (
    <div className="card">
      <div className="buttons">
        <strong>Drafts awaiting review</strong>
        <button className="secondary" onClick={load}>{rows ? "Refresh" : "Show"}</button>
      </div>
      {error && <p className="error">{error}</p>}
      {rows && rows.length === 0 && <p className="label">None waiting.</p>}
      {rows && rows.length > 0 && (
        <ul className="waiting">{rows.map((r) => (
          <li key={r.draft_id}>
            <button className="secondary" onClick={() => onOpen(r.draft_id)}>Open</button>{" "}
            patient {r.patient_id} · {r.statements} statements · by {r.created_by} · {r.draft_id}
          </li>
        ))}</ul>
      )}
    </div>
  );
}

function Scribe() {
  const [patientId, setPatientId] = useState("");
  const [transcript, setTranscript] = useState(SAMPLE);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function create(event) {
    event.preventDefault();
    setBusy(true); setError(""); setDraft(null);
    const turns = transcript.split("\n").filter((l) => l.trim()).map((line) => {
      const [who, ...rest] = line.split(":");
      const speaker = who.trim().toUpperCase().startsWith("D") ? "doctor"
        : who.trim().toUpperCase().startsWith("P") ? "patient" : "unknown";
      return { speaker, text: rest.join(":").trim() || line };
    });
    try {
      setDraft(await call("POST", "/v1/scribe/drafts?identified=true",
        { encounter_id: `enc-${Date.now()}`, patient_id: patientId, transcript: turns }));
    } catch (e) { setError(e.message); }
    setBusy(false);
  }
  async function open(id) {
    setError("");
    try { setDraft(await call("GET", `/v1/drafts/${id}?identified=true`)); }
    catch (e) { setError(e.message); }
  }
  return (
    <section>
      <Waiting onOpen={open} />
      <form className="card" onSubmit={create}>
        <label>FHIR patient id <input value={patientId} onChange={(e) => setPatientId(e.target.value)} required /></label>
        <label>Consultation transcript (D: doctor, P: patient)
          <textarea rows={8} value={transcript} onChange={(e) => setTranscript(e.target.value)} />
        </label>
        <button disabled={busy}>{busy ? "Writing the draft…" : "Create draft"}</button>
      </form>
      {error && <p className="error">{error}</p>}
      {draft && <Draft key={draft.draft_id} draft={draft} />}
    </section>
  );
}

function Audit() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  async function load() {
    try { setRows(await call("GET", "/v1/audit?limit=50")); } catch (e) { setError(e.message); }
  }
  return (
    <section className="card">
      <button onClick={load}>Load audit log</button>
      {error && <p className="error">{error}</p>}
      {rows && (
        <table>
          <thead><tr><th>seq</th><th>time</th><th>actor</th><th>action</th><th>resource</th><th>model</th><th>prompt</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.seq}><td>{r.seq}</td><td>{r.ts?.slice(0, 19)}</td><td>{r.actor} ({r.role})</td>
              <td>{r.action}</td><td>{r.resource_type} {r.resource_id}</td><td>{r.model}</td><td>{r.prompt_version}</td></tr>
          ))}</tbody>
        </table>
      )}
    </section>
  );
}

export default function App() {
  const [who, setWho] = useState(null);
  const [tab, setTab] = useState("ask");
  if (!who) return <main><h1>ClinScribe</h1><Login onLogin={(w) => { setWho(w); setTab(w.role === "doctor" ? "ask" : "audit"); }} /></main>;
  const tabs = who.role === "doctor" ? ["ask", "scribe"] : ["audit"];
  return (
    <main>
      <header>
        <h1>ClinScribe</h1>
        <nav>{tabs.map((t) => <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>{t}</button>)}</nav>
        <span className="who">{who.user} · {who.role}</span>
      </header>
      <p className="banner">Synthetic data only. Drafts are AI-generated and need a doctor's approval before anything is saved.</p>
      {tab === "ask" && <Ask />}
      {tab === "scribe" && <Scribe />}
      {tab === "audit" && <Audit />}
    </main>
  );
}
