import { useState } from "react";
import Answer from "../Answer.jsx";
import { call } from "../api.js";
import { Button, Callout, Empty, Icon, PageHeader } from "../ui.jsx";

const EXAMPLES = [
  "What is the maximum daily dose of metformin?",
  "Does clarithromycin interact with warfarin?",
  "Which gastrointestinal side effects does mazdutide cause?",
];

export default function Ask() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState([]); // newest first: {question, out, elapsed}
  const [shown, setShown] = useState(0);

  async function ask(text) {
    const q = (text ?? question).trim();
    if (q.length < 3 || busy) return;
    setBusy(true);
    setError("");
    const started = performance.now();
    try {
      const out = await call("POST", "/v1/ask?identified=true", {
        encounter_id: `ask-${Date.now()}`,
        question: q,
      });
      setHistory((all) => [{ question: q, out, elapsed: performance.now() - started }, ...all]);
      setShown(0);
      setQuestion("");
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  }

  const current = history[shown];
  return (
    <>
      <PageHeader
        title="Ask the evidence"
        description="Clinical questions answered only from the guideline corpus (WHO, FDA labels, PMC reviews, DDInter). Every sentence cites its source; when the sources do not support an answer, ClinScribe says so."
      />
      <div className="grid-2">
        <div className="stack">
          <form
            className="card composer"
            onSubmit={(event) => {
              event.preventDefault();
              ask();
            }}
          >
            <textarea
              rows={3}
              value={question}
              placeholder="Ask a clinical question, e.g. does clarithromycin interact with warfarin?"
              aria-label="Question"
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) ask();
              }}
            />
            <div className="composer-foot">
              <span className="muted small row" style={{ gap: 6 }}>
                <span className="kbd">Ctrl</span>+<span className="kbd">Enter</span>
                <span>· de-identified before any model sees it</span>
              </span>
              <span className="grow" />
              <Button type="submit" busy={busy} icon="send" disabled={question.trim().length < 3}>
                {busy ? "Searching" : "Ask"}
              </Button>
            </div>
          </form>
          <div className="row">
            <span className="muted small">Try:</span>
            {EXAMPLES.map((q) => (
              <button key={q} type="button" className="chip-suggest" onClick={() => ask(q)} disabled={busy}>
                {q}
              </button>
            ))}
          </div>
          {error && <Callout tone="danger" title="The question failed.">{error}</Callout>}
          {busy && (
            <div className="card card-body stack" aria-busy="true">
              <div className="row muted small">
                <span className="spinner" /> Searching the guidelines and checking every citation…
              </div>
              <div className="skeleton" style={{ height: 16, width: "92%" }} />
              <div className="skeleton" style={{ height: 16, width: "78%" }} />
              <div className="skeleton" style={{ height: 54, width: "100%" }} />
            </div>
          )}
          {!busy && current && (
            <Answer
              key={`${current.question}-${shown}-${history.length}`}
              data={current.out}
              sentences={current.out.identified?.sentences}
              question={current.question}
              elapsed={current.elapsed}
            />
          )}
          {!busy && !current && !error && (
            <div className="card">
              <Empty icon="ask" title="No question yet">
                Answers appear here with numbered citations. Point at a number to see its source.
              </Empty>
            </div>
          )}
        </div>
        <aside className="stack sticky">
          <div className="card">
            <div className="card-head">
              <h3>This session</h3>
              <span className="muted small">{history.length} question{history.length === 1 ? "" : "s"}</span>
            </div>
            <div className="card-body" style={{ padding: 8 }}>
              {history.length === 0 && <p className="muted small" style={{ padding: 8 }}>Questions you ask stay here until you sign out.</p>}
              {history.map((h, i) => (
                <button
                  key={history.length - i}
                  className={`history-item ${i === shown ? "on" : ""}`}
                  onClick={() => setShown(i)}
                >
                  <div className="small" style={{ fontWeight: 600 }}>{h.question}</div>
                  <div className="muted small">
                    {h.out.answer.abstained ? "No answer with evidence" : `${h.out.answer.sentences.length} cited sentence(s)`}
                    {" · "}
                    {h.out.route}
                  </div>
                </button>
              ))}
            </div>
          </div>
          <div className="card card-body stack small">
            <h3>How an answer is made</h3>
            {[
              ["shield", "The question is de-identified."],
              ["graph", "A router picks the fast path, or the agentic loop (grading, a rewrite, drug-interaction facts) for multi-step questions."],
              ["book", "Hybrid search with reranking finds the passages; the model may only use them."],
              ["check", "Guardrails check every citation, dose and drug before you see the answer."],
            ].map(([icon, text]) => (
              <div className="row" key={text} style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
                <Icon name={icon} size={16} className="muted" />
                <span className="muted">{text}</span>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </>
  );
}
