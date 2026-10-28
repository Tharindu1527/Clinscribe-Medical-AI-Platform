import { useState } from "react";
import { AiBadge, Badge, Callout, Icon, seconds } from "./ui.jsx";

// A cited answer (Ask and Voice): every sentence carries numbered citations; pointing at one lights
// up its sentence and its source, clicking opens the source passage. Abstentions say why.
const SOURCE = {
  openfda: "FDA label",
  pmc: "PMC review",
  who: "WHO guideline",
  ddinter: "DDInter",
};

export function sourceLabel(source) {
  return SOURCE[source] ?? source;
}

export function AbstainNotice({ unseen }) {
  return (
    <Callout tone="warn" title="No answer with evidence.">
      {unseen?.length
        ? `No source in the corpus mentions ${unseen.join(", ")}, so ClinScribe does not answer rather than guess.`
        : "The sources found do not support an answer. Review them directly or rephrase the question."}
    </Callout>
  );
}

export default function Answer({ data, sentences, question, elapsed, compact = false }) {
  const evidence = data.evidence ?? [];
  const [lit, setLit] = useState(null); // chunk id pointed at
  const [open, setOpen] = useState(() => new Set());
  const number = (id) => evidence.findIndex((e) => e.chunk_id === id) + 1;
  const toggle = (id) => {
    setOpen((current) => {
      const next = new Set(current);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
    document.getElementById(`src-${id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };
  const texts = sentences ?? data.answer.sentences.map((s) => s.text);
  const route = data.route;

  return (
    <div className="card fade-in">
      <div className="card-head">
        <div className="row">
          <AiBadge />
          {route && (
            <Badge tone="neutral" icon={route === "agentic" ? "graph" : "send"} title="Router decision">
              {route === "agentic" ? "Agentic path" : "Fast path"}
            </Badge>
          )}
          <Badge tone="cite" icon="book">Cite or abstain</Badge>
        </div>
        <div className="row small muted">
          {elapsed != null && (
            <span className="row" style={{ gap: 4 }}>
              <Icon name="clock" size={14} /> {seconds(elapsed)}
            </span>
          )}
          {data.answer?.model && data.answer.model !== "none" && (
            <span className="mono">{data.answer.prompt_version}</span>
          )}
        </div>
      </div>
      <div className="card-body stack">
        {question && <p className="muted small">“{question}”</p>}
        {data.answer.abstained ? (
          <AbstainNotice unseen={data.unseen_terms} />
        ) : (
          <p className="answer-text">
            {data.answer.sentences.map((s, i) => (
              <span key={i} className={`answer-sentence ${s.citations.includes(lit) ? "lit" : ""}`}>
                {texts[i]}{" "}
                {s.citations.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className={`cite ${id.startsWith("graph:") ? "graph" : ""} ${lit === id ? "on" : ""}`}
                    title={evidence[number(id) - 1]?.title ?? id}
                    onMouseEnter={() => setLit(id)}
                    onMouseLeave={() => setLit(null)}
                    onFocus={() => setLit(id)}
                    onBlur={() => setLit(null)}
                    onClick={() => toggle(id)}
                  >
                    {number(id) || "?"}
                  </button>
                ))}{" "}
              </span>
            ))}
          </p>
        )}
        {evidence.length > 0 && (
          <div className="stack" style={{ gap: 8 }}>
            <div className="row">
              <h3>Sources</h3>
              <span className="muted small">{evidence.length} passages · click a number to read it</span>
            </div>
            {evidence.map((e, i) => {
              const on = lit === e.chunk_id;
              const expanded = open.has(e.chunk_id);
              return (
                <div
                  key={e.chunk_id}
                  id={`src-${e.chunk_id}`}
                  className={`source ${on ? "on" : ""} ${expanded ? "open" : ""}`}
                  onMouseEnter={() => setLit(e.chunk_id)}
                  onMouseLeave={() => setLit(null)}
                >
                  <div className="source-head" onClick={() => toggle(e.chunk_id)}>
                    <span className="source-n">{i + 1}</span>
                    <div className="grow">
                      <div className="source-title">{e.title}</div>
                      <div className="source-section">
                        {sourceLabel(e.source)} · {e.section}
                      </div>
                    </div>
                    {e.source_url && (
                      <a
                        className="btn btn-ghost btn-sm btn-icon"
                        href={e.source_url}
                        target="_blank"
                        rel="noreferrer"
                        title="Open the source"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <Icon name="external" size={15} />
                      </a>
                    )}
                    <Icon name="chevron" size={16} className="muted source-chevron" strokeWidth={2.2} />
                  </div>
                  {expanded && <div className="source-text fade-in">{e.text}</div>}
                </div>
              );
            })}
          </div>
        )}
        {!compact && <SafetyChecks data={data} />}
      </div>
    </div>
  );
}

function SafetyChecks({ data }) {
  const events = data.events ?? [];
  const violations = data.violations ?? [];
  const dropped = data.dropped ?? [];
  if (!events.length && !violations.length && !dropped.length) return null;
  return (
    <details className="card" style={{ background: "var(--surface-2)" }}>
      <summary className="card-body row small">
        <Icon name="shield" size={16} />
        <strong>How this answer was checked</strong>
        <span className="muted">
          {violations.length ? `${violations.length} guardrail note(s)` : "guardrails passed"}
          {dropped.length ? ` · ${dropped.length} passage(s) dropped` : ""}
        </span>
      </summary>
      <div className="card-body stack" style={{ paddingTop: 0 }}>
        {events.length > 0 && (
          <div className="timeline">
            {events.map((e, i) => (
              <Badge key={i} tone="neutral">
                {i + 1}. {e}
              </Badge>
            ))}
          </div>
        )}
        {violations.map((v, i) => (
          <Callout key={i} tone="warn">{v}</Callout>
        ))}
        {dropped.map((d, i) => (
          <Callout key={i} tone="danger" title="Dropped (possible injection):">{d}</Callout>
        ))}
      </div>
    </details>
  );
}
