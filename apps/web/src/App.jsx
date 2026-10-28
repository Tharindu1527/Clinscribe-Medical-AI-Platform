import { lazy, Suspense, useEffect, useState } from "react";
import { DEMO, setToken } from "./api.js";
import Ask from "./pages/Ask.jsx";
import Audit from "./pages/Audit.jsx";
import Lab from "./pages/Lab.jsx";
import Login from "./pages/Login.jsx";
import Scribe from "./pages/Scribe.jsx";
import { Badge, Icon } from "./ui.jsx";
// loaded on first use: the LiveKit client is most of the bundle (ADR-0019)
const Voice = lazy(() => import("./pages/Voice.jsx"));

const PAGES = {
  ask: { label: "Ask", icon: "ask", hint: "Evidence" },
  voice: { label: "Voice", icon: "voice", hint: "WebRTC" },
  scribe: { label: "Scribe", icon: "scribe", hint: "Notes" },
  lab: { label: "Lab", icon: "lab", hint: "Results" },
  audit: { label: "Audit log", icon: "audit", hint: "Records" },
};
const BY_ROLE = { doctor: ["ask", "voice", "scribe", "lab"], admin: ["audit"], operator: ["audit"] };

function useTheme() {
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("clinscribe-theme") ?? "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("clinscribe-theme", theme);
    } catch {
      /* private window: the choice lasts for this tab */
    }
  }, [theme]);
  const dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  return [dark, () => setTheme(dark ? "light" : "dark")];
}

export default function App() {
  const [who, setWho] = useState(null);
  const [page, setPage] = useState("ask");
  const [dark, toggleTheme] = useTheme();

  if (!who) {
    return (
      <Login
        onLogin={(w) => {
          setWho(w);
          setPage(BY_ROLE[w.role][0]);
        }}
      />
    );
  }
  const pages = BY_ROLE[who.role] ?? [];
  const initials = who.user.split("-").map((part) => part[0]).join("").slice(0, 2).toUpperCase();

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Icon name="logo" size={20} strokeWidth={2.4} />
          </div>
          <div>
            <div className="brand-name">ClinScribe</div>
            <div className="brand-sub">Voice clinical copilot</div>
          </div>
        </div>
        <nav className="nav" aria-label="Main">
          <div className="nav-label">{who.role === "doctor" ? "Clinical" : "Oversight"}</div>
          {pages.map((key) => (
            <button
              key={key}
              className={`nav-item ${page === key ? "active" : ""}`}
              aria-current={page === key ? "page" : undefined}
              onClick={() => setPage(key)}
            >
              <Icon name={PAGES[key].icon} size={18} />
              {PAGES[key].label}
              <span className="nav-hint">{PAGES[key].hint}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="user-card">
            <span className="avatar">{initials}</span>
            <div className="grow">
              <div className="user-name">{who.user}</div>
              <div className="user-role">{who.role}</div>
            </div>
          </div>
          <div className="row" style={{ gap: 6 }}>
            <button className="btn btn-ghost btn-sm btn-icon" onClick={toggleTheme} title={dark ? "Light theme" : "Dark theme"} aria-label="Switch theme">
              <Icon name={dark ? "sun" : "moon"} size={16} />
            </button>
            <button
              className="btn btn-ghost btn-sm grow"
              onClick={() => {
                setToken(null);
                setWho(null);
              }}
            >
              <Icon name="logout" size={15} /> Sign out
            </button>
          </div>
        </div>
      </aside>
      <div className="main">
        <div className="topbar">
          <span className="notice">
            <Icon name="shield" size={15} /> Synthetic data only · AI drafts need a doctor's approval before anything is saved
          </span>
          <span className="spacer" />
          {DEMO && (
            <Badge tone="warn" icon="info" title="Recorded responses; nothing is saved">
              Demo data
            </Badge>
          )}
        </div>
        <main className="content">
          {page === "ask" && <Ask />}
          {page === "voice" && (
            <Suspense fallback={<div className="skeleton" style={{ height: 240 }} />}>
              <Voice />
            </Suspense>
          )}
          {page === "scribe" && <Scribe />}
          {page === "lab" && <Lab />}
          {page === "audit" && <Audit />}
        </main>
      </div>
    </div>
  );
}
