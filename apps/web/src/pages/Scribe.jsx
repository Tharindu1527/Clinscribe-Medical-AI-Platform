import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { call } from "../api.js";
import {
  AiBadge,
  AutoText,
  Badge,
  Button,
  Callout,
  Empty,
  Icon,
  PageHeader,
  Stat,
  percent,
} from "../ui.jsx";

const SECTIONS = ["subjective", "objective", "assessment", "plan"];
const SAMPLE = `D: Good morning, what brings you in today?
P: I have been really thirsty and tired for about three weeks.
D: Your fasting glucose this morning was 9.1 mmol/L.
D: This fits type 2 diabetes; I would like to confirm with an HbA1c.
D: Let's start metformin 500 mg once daily with the evening meal.
D: We will review you in four weeks with the HbA1c result.`;

function parseTranscript(text) {
  return text
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      const [who, ...rest] = line.split(":");
      const tag = who.trim().toUpperCase();
      const speaker = tag.startsWith("D") ? "doctor" : tag.startsWith("P") ? "patient" : "unknown";
      return { speaker, text: rest.join(":").trim() || line };
    });
}

export default function Scribe() {
  const [draft, setDraft] = useState(null);
  const [patient, setPatient] = useState("");
  const [error, setError] = useState("");

  async function open(row) {
    setError("");
    try {
      setDraft(await call("GET", `/v1/drafts/${row.draft_id}?identified=true`));
      setPatient(row.patient_id);
    } catch (e) {
      setError(e.message);
    }
  }

  if (draft) {
    return (
      <DraftReview
        key={draft.draft_id}
        draft={draft}
        patient={patient}
        onBack={() => setDraft(null)}
      />
    );
  }
  return (
    <>
      <PageHeader
        title="Scribe"
        description="Consultations become SOAP drafts: every statement points to the turns it came from, and nothing reaches the record until you approve it with two patient identifiers."
      />
      {error && <Callout tone="danger" title="Could not open the draft.">{error}</Callout>}
      <div className="grid-2">
        <NewDraft
          onDraft={(d, p) => {
            setDraft(d);
            setPatient(p);
          }}
        />
        <Waiting onOpen={open} />
      </div>
    </>
  );
}

function NewDraft({ onDraft }) {
  const [patientId, setPatientId] = useState("1617");
  const [transcript, setTranscript] = useState(SAMPLE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const turns = useMemo(() => parseTranscript(transcript), [transcript]);

  async function create(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const out = await call("POST", "/v1/scribe/drafts?identified=true", {
        encounter_id: `enc-${Date.now()}`,
        patient_id: patientId,
        transcript: turns,
      });
      onDraft(out, patientId);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={create}>
      <div className="card-head">
        <h2>New draft from a transcript</h2>
        <Badge tone="neutral" icon="voice" title="Drafts from consultation audio: just scribe <patient id>">or from audio</Badge>
      </div>
      <div className="card-body stack">
        <label className="field" style={{ maxWidth: 240 }}>
          FHIR patient id
          <input value={patientId} onChange={(e) => setPatientId(e.target.value)} required pattern="[A-Za-z0-9._\-]{1,64}" />
        </label>
        <label className="field">
          <span className="row" style={{ justifyContent: "space-between" }}>
            Consultation transcript
            <span className="field-hint">one turn per line · D: doctor · P: patient</span>
          </span>
          <textarea rows={9} value={transcript} onChange={(e) => setTranscript(e.target.value)} className="mono" style={{ fontSize: "0.85rem" }} />
        </label>
        <div className="row">
          <span className="muted small">
            {turns.length} turns · {turns.filter((t) => t.speaker === "doctor").length} doctor ·{" "}
            {turns.filter((t) => t.speaker === "patient").length} patient
          </span>
          <span className="grow" />
          <Button variant="ghost" type="button" size="sm" onClick={() => setTranscript(SAMPLE)}>
            Reset sample
          </Button>
          <Button type="submit" busy={busy} icon="sparkles" disabled={!turns.length}>
            {busy ? "Writing the draft" : "Create draft"}
          </Button>
        </div>
        {busy && (
          <p className="muted small">The note writer drafts, then guardrails check sources, doses and wording. This can take a minute on free tiers.</p>
        )}
        {error && <Callout tone="danger" title="No draft.">{error}</Callout>}
      </div>
    </form>
  );
}

function Waiting({ onOpen }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  async function load() {
    setError("");
    try {
      setRows(await call("GET", "/v1/drafts"));
    } catch (e) {
      setError(e.message);
    }
  }
  useEffect(() => {
    load();
  }, []);
  return (
    <div className="card">
      <div className="card-head">
        <h2>Awaiting your review</h2>
        <Button variant="ghost" size="sm" icon="refresh" onClick={load}>
          Refresh
        </Button>
      </div>
      {error && <div className="card-body"><Callout tone="danger">{error}</Callout></div>}
      {rows === null && !error && (
        <div className="card-body stack">
          <div className="skeleton" style={{ height: 38 }} />
          <div className="skeleton" style={{ height: 38 }} />
        </div>
      )}
      {rows?.length === 0 && (
        <Empty icon="check" title="Nothing waiting">
          Drafts from the Scribe listener appear here.
        </Empty>
      )}
      {rows?.length > 0 && (
        <div className="draft-list">
          {rows.map((r) => (
            <div className="draft-row" key={r.draft_id}>
              <span className="avatar"><Icon name="scribe" size={16} /></span>
              <div className="grow">
                <div className="user-name">Patient {r.patient_id}</div>
                <div className="muted small">
                  {r.statements} statements · by {r.created_by} · <span className="mono">{r.draft_id}</span>
                </div>
              </div>
              <Button variant="secondary" size="sm" onClick={() => onOpen(r)}>
                Review
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Unsure words (ADR-0027) marked inside a transcript turn.
function TurnText({ text, unsure }) {
  if (!unsure?.length) return text;
  const byWord = new Map(unsure.map((u) => [u.word.toLowerCase(), u]));
  const pattern = new RegExp(`\\b(${[...byWord.keys()].map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\b`, "gi");
  return text.split(pattern).map((part, i) => {
    const hit = byWord.get(part.toLowerCase());
    return hit ? (
      <mark key={i} className="unsure" title={`Speech recognition ${percent(hit.confidence)} sure`}>
        {part}
      </mark>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    );
  });
}

// The doctor reads and edits the originals (re-identified by the API, audited; ADR-0015);
// "What the AI saw" shows the surrogate text the models worked on.
function DraftReview({ draft, patient, onBack }) {
  const shown = draft.identified
    ? draft.draft.statements.map((s, i) => ({ ...s, text: draft.identified.statements[i] }))
    : draft.draft.statements;
  const [statements, setStatements] = useState(shown);
  const [modelView, setModelView] = useState(false);
  const [focus, setFocus] = useState(null);
  const [birthDate, setBirthDate] = useState("");
  const [family, setFamily] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [refused, setRefused] = useState(draft.refused ? `${draft.refused}.` : "");
  const turnRefs = useRef([]);

  const transcript = modelView ? draft.transcript : draft.identified?.transcript ?? draft.transcript;
  const unsureTurns = draft.unsure_speech?.turns ?? [];
  const speech = draft.unsure_speech?.statements ?? [];
  const unsupportedText = new Set(draft.unsupported.map((s) => s.text));
  const unsupported = new Set(draft.draft.statements.flatMap((s, i) => (unsupportedText.has(s.text) ? [i] : [])));
  const unsure = new Set(speech.flatMap((f, i) => (f.heard.length || f.changed ? [i] : [])));
  const editedIdx = new Set(statements.flatMap((s, i) => (s.text !== shown[i].text ? [i] : [])));
  const edited = editedIdx.size > 0;
  const litTurns = new Set(focus === null ? [] : statements[focus].transcript_turns);
  const done = !!result;

  useEffect(() => {
    if (focus === null) return;
    const first = statements[focus].transcript_turns[0];
    turnRefs.current[first]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focus]); // eslint-disable-line react-hooks/exhaustive-deps

  async function decide(decision) {
    setError("");
    setBusy(decision);
    const body = { decision, birth_date: birthDate || null, family_name: family || null };
    if (decision === "edit") {
      body.edited = { ...draft.draft, statements };
      body.edited_identified = !!draft.identified;
    }
    if (decision === "reject") body.reason = reason || "rejected by the doctor";
    try {
      const out = await call("POST", `/v1/drafts/${draft.draft_id}/review`, body);
      if (out.awaiting_review) {
        setRefused(
          `${out.result.reason}. Check the identifiers and try again (${out.attempts_left} attempt${out.attempts_left === 1 ? "" : "s"} left).`,
        );
      } else {
        setRefused("");
        setResult(out.result);
      }
    } catch (e) {
      setError(e.message);
    }
    setBusy("");
  }

  return (
    <>
      <div className="page-header">
        <div className="stack" style={{ gap: 8 }}>
          <Button variant="ghost" size="sm" icon="back" onClick={onBack} style={{ alignSelf: "flex-start" }}>
            Back to Scribe
          </Button>
          <div className="row">
            <h1>Draft note{patient ? ` · patient ${patient}` : ""}</h1>
            <AiBadge />
          </div>
          <p className="muted small mono">
            {draft.draft_id} · {draft.draft.prompt_version} · {draft.draft.model}
          </p>
        </div>
        {draft.identified && (
          <div className="segmented" role="tablist" aria-label="View">
            <button className={!modelView ? "on" : ""} onClick={() => setModelView(false)}>
              Doctor's view
            </button>
            <button className={modelView ? "on" : ""} onClick={() => setModelView(true)}>
              What the AI saw
            </button>
          </div>
        )}
      </div>

      <div className="stack">
        <div className="stats">
          <Stat value={draft.draft.statements.length} label="statements" />
          <Stat value={unsupported.size} label="without a guideline source" tone={unsupported.size ? "warn" : ""} />
          <Stat value={unsure.size} label="rely on unsure speech" tone={unsure.size ? "speech" : ""} />
          <Stat value={draft.removed.length} label="removed by guardrails" tone={draft.removed.length ? "danger" : ""} />
        </div>
        {unsure.size > 0 && (
          <Callout tone="speech" title={`${unsure.size} statement${unsure.size === 1 ? " relies" : "s rely"} on speech the recogniser was unsure of.`}>
            Check them against the consultation before approving. Unsure words are underlined in the transcript.
          </Callout>
        )}
        {modelView && (
          <Callout tone="info" title="What the AI saw.">
            Names, dates and places as surrogates (PERSON_1, DATE_1). Read only.
          </Callout>
        )}
        {draft.removed.length > 0 && (
          <details className="callout callout-danger" style={{ display: "block" }}>
            <summary>
              <strong>{draft.removed.length} statement(s) removed by guardrails</strong> (show)
            </summary>
            <ul>{draft.removed.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </details>
        )}

        <div className="grid-2">
          <div className="card card-body">
            {SECTIONS.map((section) => {
              const items = statements.map((s, i) => [s, i]).filter(([s]) => s.section === section);
              if (!items.length) return null;
              return (
                <div key={section} className="section-block">
                  <div className="section-title">
                    {section}
                    <span className="badge badge-neutral">{items.length}</span>
                  </div>
                  {items.map(([s, i]) => (
                    <div
                      key={i}
                      className={`statement ${focus === i ? "focus" : ""} ${unsure.has(i) ? "unsure" : ""} ${unsupported.has(i) ? "unsupported" : ""}`}
                      onMouseEnter={() => setFocus(i)}
                      onMouseLeave={() => setFocus((f) => (f === i ? null : f))}
                    >
                      <AutoText
                        value={modelView ? draft.draft.statements[i].text : s.text}
                        disabled={done || modelView}
                        aria-label={`${section} statement ${i + 1}`}
                        onFocus={() => setFocus(i)}
                        onChange={(e) =>
                          setStatements(statements.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))
                        }
                      />
                      <div className="meta">
                        {s.transcript_turns.map((t) => (
                          <Badge key={t} tone="neutral" title={transcript[t]}>turn {t}</Badge>
                        ))}
                        {s.citations.length > 0 && <Badge tone="cite" icon="book">{s.citations.length} source(s)</Badge>}
                        {unsupported.has(i) && <Badge tone="warn" icon="alert">No guideline source</Badge>}
                        {speech[i]?.heard.map((u) => (
                          <Badge key={u.word} tone="speech" icon="wave" title={`Speech recognition ${percent(u.confidence)} sure (turn ${u.turn})`}>
                            Unsure speech: “{u.word}” {percent(u.confidence)}
                          </Badge>
                        ))}
                        {speech[i]?.changed && (
                          <Badge
                            tone="speech"
                            icon="alert"
                            title={`The recogniser was unsure of ${speech[i].changed.unsure.map((u) => `“${u.word}”`).join(", ")}`}
                          >
                            Check: {speech[i].changed.terms.join(", ")} not in the cited speech
                          </Badge>
                        )}
                        {editedIdx.has(i) && !modelView && (
                          <>
                            <span className="edited">Edited</span>
                            <button
                              className="btn btn-ghost btn-sm"
                              style={{ height: 22 }}
                              disabled={done}
                              onClick={() => setStatements(statements.map((x, j) => (j === i ? shown[i] : x)))}
                            >
                              Undo
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
          <div className="card sticky">
            <div className="card-head">
              <h3>Transcript</h3>
              <span className="muted small">point at a statement to see its turns</span>
            </div>
            <div className="card-body stack" style={{ gap: 2, maxHeight: "62vh", overflowY: "auto" }}>
              {transcript.map((turn, t) => {
                const [who, ...rest] = turn.split(": ");
                const role = who.toLowerCase();
                return (
                  <div key={t} ref={(el) => (turnRefs.current[t] = el)} className={`turn ${litTurns.has(t) ? "lit" : ""}`}>
                    <span className={`turn-who ${["doctor", "patient"].includes(role) ? role : "unknown"}`} title={role}>
                      {role === "doctor" ? "D" : role === "patient" ? "P" : "?"}
                    </span>
                    <div className="turn-text">
                      <span className="turn-n">{t}</span>
                      <TurnText text={rest.join(": ") || turn} unsure={unsureTurns[t]} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {error && <Callout tone="danger" title="The review failed.">{error}</Callout>}
        {result ? (
          result.status === "written" ? (
            <Callout tone="ok" title="Approved and saved.">
              FHIR {result.resource_type}/<span className="mono">{result.resource_id}</span>
              {edited ? " with your edits (kept, de-identified, as evaluation data)." : "."}
            </Callout>
          ) : (
            <Callout tone="warn" title={`Draft ${result.status}.`}>{result.reason}</Callout>
          )
        ) : (
          <div className="approve-bar">
            <div className="stack grow" style={{ gap: 4, minWidth: 220 }}>
              <strong className="small">Confirm the patient to approve</strong>
              <span className="muted small">Two identifiers are checked against the record before anything is written.</span>
              {refused && <span className="small refusal" style={{ color: "var(--danger)" }}>{refused}</span>}
            </div>
            <label className="field">
              Birth date
              <input type="date" value={birthDate} onChange={(e) => setBirthDate(e.target.value)} />
            </label>
            <label className="field">
              Family name
              <input value={family} onChange={(e) => setFamily(e.target.value)} placeholder="as in the record" />
            </label>
            {rejecting ? (
              <>
                <label className="field">
                  Reason
                  <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="why reject" autoFocus />
                </label>
                <Button variant="danger" busy={busy === "reject"} onClick={() => decide("reject")}>Reject draft</Button>
                <Button variant="ghost" onClick={() => setRejecting(false)}>Cancel</Button>
              </>
            ) : (
              <>
                <Button variant="danger" icon="x" onClick={() => setRejecting(true)}>Reject</Button>
                <Button
                  icon="check"
                  busy={busy === "approve" || busy === "edit"}
                  disabled={!birthDate || !family.trim()}
                  onClick={() => decide(edited ? "edit" : "approve")}
                >
                  {edited ? `Approve with ${editedIdx.size} edit${editedIdx.size === 1 ? "" : "s"}` : "Approve"}
                </Button>
              </>
            )}
          </div>
        )}
      </div>
    </>
  );
}
