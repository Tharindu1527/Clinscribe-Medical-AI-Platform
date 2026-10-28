import { useState } from "react";
import { call, DEMO, setToken } from "../api.js";
import { Badge, Button, Callout, Icon } from "../ui.jsx";

const USERS = [
  { user: "dr-demo", role: "doctor", name: "Dr Demo", note: "Ask, voice, Scribe and Lab" },
  { user: "dr-second", role: "doctor", name: "Dr Second", note: "A second doctor, for the audit trail" },
  { user: "admin-demo", role: "admin", name: "Admin Demo", note: "Audit log" },
  { user: "ops-demo", role: "operator", name: "Ops Demo", note: "Audit log" },
];

const POINTS = [
  ["shield", "De-identified before any model", "Names, dates and identifiers become surrogates before a prompt, a log or a trace."],
  ["book", "Every clinical claim is cited", "Answers come only from guideline sources, or ClinScribe says it cannot answer."],
  ["check", "You approve every write", "Drafts and lab values reach the record only after your review and two identifiers."],
];

export default function Login({ onLogin }) {
  const [user, setUser] = useState("dr-demo");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { token, role } = await call("POST", "/v1/dev/login", { user });
      setToken(token);
      onLogin({ user, role });
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <section className="login-hero">
        <div className="brand" style={{ padding: 0 }}>
          <div className="brand-mark">
            <Icon name="logo" size={20} strokeWidth={2.4} />
          </div>
          <div>
            <div className="brand-name" style={{ color: "#fff" }}>ClinScribe</div>
            <div className="brand-sub" style={{ color: "#9fb3d1" }}>Voice clinical copilot</div>
          </div>
        </div>
        <div className="stack" style={{ gap: 18 }}>
          <h1>Notes, answers and lab results you can check.</h1>
          <p>
            ClinScribe drafts the SOAP note from the consultation, answers clinical questions from
            guidelines with a source on every sentence, and reads lab reports. The doctor decides.
          </p>
        </div>
        <div className="hero-points">
          {POINTS.map(([icon, title, text]) => (
            <div className="hero-point" key={title}>
              <Icon name={icon} size={18} />
              <div>
                <strong>{title}</strong>
                <span style={{ color: "#a9bbd6" }}>{text}</span>
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className="login-panel">
        <form className="login-box" onSubmit={submit}>
          <div className="stack" style={{ gap: 6 }}>
            <h2>Sign in</h2>
            <p className="muted small">Synthetic demo users. No real patient data is used anywhere.</p>
          </div>
          {DEMO && (
            <Callout tone="info" title="Demo mode.">
              Answers come from responses recorded from the real system; nothing is saved.
            </Callout>
          )}
          <div className="stack" style={{ gap: 8 }} role="radiogroup" aria-label="User">
            {USERS.map((u) => (
              <button
                type="button"
                role="radio"
                aria-checked={user === u.user}
                key={u.user}
                className={`user-option ${user === u.user ? "on" : ""}`}
                onClick={() => setUser(u.user)}
              >
                <span className="avatar">{u.name.split(" ").map((w) => w[0]).join("")}</span>
                <span className="grow">
                  <span className="user-name">{u.name}</span>
                  <span className="muted small" style={{ display: "block" }}>{u.note}</span>
                </span>
                <Badge tone={u.role === "doctor" ? "ai" : "neutral"}>{u.role}</Badge>
              </button>
            ))}
          </div>
          <Button type="submit" busy={busy} icon="send">Continue as {USERS.find((u) => u.user === user).name}</Button>
          {error && (
            <Callout tone="danger" title="Could not sign in.">
              {error}. Demo sign-in must be on in the API (<code>DEV_LOGIN=true</code> in{" "}
              <code>.env</code>, then <code>just up</code>), or try the UI with{" "}
              <code>npm run dev:demo</code>.
            </Callout>
          )}
        </form>
      </section>
    </div>
  );
}
