import { useRef, useState } from "react";
import { call, DEMO } from "../api.js";
import { Badge, Button, Callout, Empty, Icon, PageHeader } from "../ui.jsx";

// Lab mode (SPEC section 2): a report PDF or an HL7 v2 ORU^R01 message becomes preliminary FHIR
// Observations with flags; nothing is written until the doctor confirms the values (each one with
// its own approval, after the two-identifier check). No model sees lab values.
const IDENTITY = { name: "Name", birth_date: "Birth date", mrn: "MRN" };

function readBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function RangeBar({ value, low, high }) {
  if (low == null || high == null || high <= low) return <span className="muted">-</span>;
  const pos = Math.min(98, Math.max(2, 25 + ((value - low) / (high - low)) * 50));
  const out = value < low || value > high;
  return (
    <span className="range" title={`Reference ${low} to ${high}`}>
      <span className="range-ok" />
      <span className={`range-dot ${out ? "out" : ""}`} style={{ left: `${pos}%` }} />
    </span>
  );
}

function row(obs) {
  const q = obs.valueQuantity ?? {};
  const range = obs.referenceRange?.[0];
  const flag = obs.interpretation?.[0]?.coding?.[0]?.code ?? "N";
  return {
    name: obs.code?.coding?.[0]?.display ?? "?",
    loinc: obs.code?.coding?.[0]?.code,
    value: q.value,
    unit: q.unit,
    low: range?.low?.value,
    high: range?.high?.value,
    flag,
  };
}

export default function Lab() {
  const [mode, setMode] = useState("pdf");
  const [patientId, setPatientId] = useState("");
  const [file, setFile] = useState(null);
  const [message, setMessage] = useState("");
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [parsed, setParsed] = useState(null);
  const [chosen, setChosen] = useState(new Set());
  const [birthDate, setBirthDate] = useState("");
  const [family, setFamily] = useState("");
  const [confirmed, setConfirmed] = useState(null);
  const input = useRef(null);

  const ready = patientId.trim() && (mode === "pdf" ? file : message.trim().length > 10);

  async function parse(event) {
    event.preventDefault();
    setBusy("parse");
    setError("");
    setParsed(null);
    setConfirmed(null);
    try {
      const body = { patient_id: patientId.trim() };
      if (mode === "pdf") body.pdf_base64 = await readBase64(file);
      else body.hl7_message = message;
      const out = await call("POST", "/v1/lab/parse", body);
      setParsed(out);
      setChosen(new Set(out.observations.map((_, i) => i)));
    } catch (e) {
      setError(e.message);
    }
    setBusy("");
  }

  async function confirm() {
    setBusy("confirm");
    setError("");
    try {
      setConfirmed(
        await call("POST", `/v1/lab/${parsed.lab_id}/confirm`, {
          birth_date: birthDate,
          family_name: family,
          indexes: [...chosen].sort((a, b) => a - b),
        }),
      );
    } catch (e) {
      setError(e.message);
    }
    setBusy("");
  }

  async function loadDemo() {
    const { demoLab } = await import("../demo/mock.js");
    setMode("hl7");
    setPatientId(demoLab.patientId);
    setMessage(demoLab.message);
  }

  const rows = parsed?.observations.map(row) ?? [];
  const identityOk = parsed && Object.values(parsed.identity).every(Boolean);
  const abnormal = rows.filter((r) => r.flag !== "N").length;

  return (
    <>
      <PageHeader
        title="Lab results"
        description="Read a lab report into preliminary results with high and low flags. The report must match the patient on record, and nothing is saved until you confirm the values."
      >
        {DEMO && (
          <Button variant="secondary" icon="lab" onClick={loadDemo}>
            Load the demo message
          </Button>
        )}
      </PageHeader>
      <div className="stack">
        <form className="card" onSubmit={parse}>
          <div className="card-head">
            <h2>Report</h2>
            <div className="segmented" role="tablist" aria-label="Report format">
              <button type="button" className={mode === "pdf" ? "on" : ""} onClick={() => setMode("pdf")}>
                PDF report
              </button>
              <button type="button" className={mode === "hl7" ? "on" : ""} onClick={() => setMode("hl7")}>
                HL7 v2 message
              </button>
            </div>
          </div>
          <div className="card-body stack">
            <label className="field" style={{ maxWidth: 240 }}>
              FHIR patient id
              <input value={patientId} onChange={(e) => setPatientId(e.target.value)} placeholder="e.g. 1617" required />
            </label>
            {mode === "pdf" ? (
              <div
                className={`dropzone ${drag ? "drag" : ""}`}
                role="button"
                tabIndex={0}
                onClick={() => input.current?.click()}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDrag(true);
                }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDrag(false);
                  if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
                }}
              >
                <Icon name="upload" size={26} />
                <strong>{file ? file.name : "Drop a lab report PDF here"}</strong>
                <span className="small">{file ? `${Math.round(file.size / 1024)} KB · click to choose another` : "or click to choose a file"}</span>
                <input
                  ref={input}
                  type="file"
                  accept="application/pdf"
                  hidden
                  onChange={(e) => e.target.files[0] && setFile(e.target.files[0])}
                />
              </div>
            ) : (
              <label className="field">
                ORU^R01 message
                <textarea
                  rows={8}
                  className="mono"
                  style={{ fontSize: "0.78rem" }}
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="MSH|^~\&|..."
                />
              </label>
            )}
            <div className="row">
              <span className="muted small">Parsed by rules, not by a model: values are read exactly.</span>
              <span className="grow" />
              <Button type="submit" icon="lab" busy={busy === "parse"} disabled={!ready}>
                Read the report
              </Button>
            </div>
            {error && <Callout tone="danger" title="Not read.">{error}</Callout>}
          </div>
        </form>

        <div className="stack">
          {!parsed && (
            <div className="card">
              <Empty icon="lab" title="No report read yet">
                Values appear here with their reference ranges. Choose which to confirm.
              </Empty>
            </div>
          )}
          {parsed && (
            <div className="card fade-in">
              <div className="card-head">
                <div className="row">
                  <h2>Preliminary results</h2>
                  {abnormal > 0 && <Badge tone="danger" icon="alert">{abnormal} abnormal</Badge>}
                </div>
                <span className="muted small">collected {parsed.collected ?? "?"}</span>
              </div>
              <div className="card-body stack">
                <div className="check-list">
                  {Object.entries(parsed.identity).map(([key, ok]) => (
                    <Badge key={key} tone={ok ? "ok" : "danger"} icon={ok ? "check" : "x"}>
                      {IDENTITY[key] ?? key} {ok ? "matches" : "does not match"}
                    </Badge>
                  ))}
                </div>
                {!identityOk && (
                  <Callout tone="danger" title="This report does not match the patient on record.">
                    Confirming is blocked. Check the patient id and the report.
                  </Callout>
                )}
              </div>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th style={{ width: 34 }}>
                        <input
                          type="checkbox"
                          aria-label="Select all"
                          checked={chosen.size === rows.length && rows.length > 0}
                          onChange={(e) => setChosen(new Set(e.target.checked ? rows.map((_, i) => i) : []))}
                          disabled={!!confirmed}
                        />
                      </th>
                      <th>Test</th>
                      <th className="num">Value</th>
                      <th>Unit</th>
                      <th>Reference</th>
                      <th>Flag</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i}>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`Confirm ${r.name}`}
                            checked={chosen.has(i)}
                            disabled={!!confirmed}
                            onChange={(e) => {
                              const next = new Set(chosen);
                              e.target.checked ? next.add(i) : next.delete(i);
                              setChosen(next);
                            }}
                          />
                        </td>
                        <td>
                          <div style={{ fontWeight: 600 }}>{r.name}</div>
                          <div className="muted small mono">LOINC {r.loinc}</div>
                        </td>
                        <td className={`num ${r.flag === "H" ? "flag-h" : r.flag === "L" ? "flag-l" : ""}`}>
                          {Number(r.value).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                        </td>
                        <td className="mono small">{r.unit}</td>
                        <td>
                          <div className="row" style={{ flexWrap: "nowrap" }}>
                            <RangeBar value={r.value} low={r.low} high={r.high} />
                            <span className="muted small">
                              {r.low}–{r.high}
                            </span>
                          </div>
                        </td>
                        <td>
                          {r.flag === "H" ? (
                            <Badge tone="danger">High</Badge>
                          ) : r.flag === "L" ? (
                            <Badge tone="ai">Low</Badge>
                          ) : (
                            <Badge tone="ok">Normal</Badge>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="card-body stack">
                {parsed.not_mapped.length > 0 && (
                  <Callout tone="warn" title="Read but not mapped:">{parsed.not_mapped.join("; ")}</Callout>
                )}
                {parsed.unreadable_rows.length > 0 && (
                  <Callout tone="warn" title="Rows that could not be read:">{parsed.unreadable_rows.join("; ")}</Callout>
                )}
                {confirmed ? (
                  <Callout tone={confirmed.refused.length ? "warn" : "ok"} title={`${confirmed.written.length} value(s) saved as final Observations.`}>
                    {confirmed.written.map((id) => (
                      <span key={id} className="mono small" style={{ marginRight: 8 }}>Observation/{id}</span>
                    ))}
                    {confirmed.refused.length > 0 && <div>Refused: {confirmed.refused.join("; ")}</div>}
                  </Callout>
                ) : (
                  <div className="row" style={{ alignItems: "flex-end" }}>
                    <label className="field">
                      Birth date
                      <input type="date" value={birthDate} onChange={(e) => setBirthDate(e.target.value)} />
                    </label>
                    <label className="field">
                      Family name
                      <input value={family} onChange={(e) => setFamily(e.target.value)} placeholder="as in the record" />
                    </label>
                    <span className="grow" />
                    <Button
                      icon="check"
                      busy={busy === "confirm"}
                      disabled={!identityOk || !chosen.size || !birthDate || !family.trim()}
                      onClick={confirm}
                    >
                      Confirm {chosen.size} value{chosen.size === 1 ? "" : "s"}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
