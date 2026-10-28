# ClinScribe review UI

React 19 + Vite, plain CSS, no UI framework and no external requests (fonts and icons are local).
The doctor's screens for every mode, and the audit log for admins and operators:

| Page | Who | What it does |
|---|---|---|
| Ask | doctor | A question, an answer with a numbered citation on every sentence; pointing at a number lights up its sentence and source, clicking opens the passage. Abstentions say why. The session keeps earlier questions. |
| Voice | doctor | WebRTC to the self-hosted LiveKit server and the voice agent (ADR-0019): live transcript, and each spoken answer with its sources. |
| Scribe | doctor | Drafts awaiting review, a new draft from a typed transcript, and the review: the SOAP note beside the transcript (a statement lights up the turns it cites), flags for statements without a guideline source and for unsure speech (ADR-0027), edits with undo, "what the AI saw" (surrogates), approval with two identifiers or rejection. |
| Lab | doctor | A PDF report or an HL7 v2 ORU^R01 message read into preliminary results: identity checks, values with reference ranges and flags, the values to confirm. |
| Audit log | admin, operator | Search and filter the hash-chained audit rows. |

Light and dark themes follow the system until the theme button picks one; the layout works down
to phone width.

## Run it

| | Command | Needs |
|---|---|---|
| Against the API | `npm --prefix apps/web run dev`, then http://127.0.0.1:5173 | `just up rag`; demo sign-in on in the API (`DEV_LOGIN=true` in `.env`, then `just up`) |
| Demo mode | `just ui-demo`, then http://127.0.0.1:5174 | nothing: no stack, no keys |

The dev server proxies `/v1` to the API at 127.0.0.1:8000, so the browser talks to one origin. The
token stays in memory only.

**Demo mode** (`vite --mode demo`) answers from responses recorded from the real API on synthetic
data (`src/demo/fixtures.json`: guideline questions on the fast and agentic paths and an
abstention, a synthetic consultation's draft with unsure speech, a Synthea patient's lab panel as an
HL7 message, audit rows of the demo users). Nothing is sent anywhere and nothing is saved;
identifiers are not checked; voice is not available. Every screen shows a "Demo data" badge.
Re-record the data with `just ui-fixtures` (needs the stack).

## Code

```text
src/
  App.jsx          shell: sidebar navigation by role, theme, sign-out
  api.js           fetch wrapper; demo mode switch
  ui.jsx           icons (drawn for this app), buttons, badges, callouts, stats
  Answer.jsx       a cited answer with linked sources (Ask and Voice)
  pages/           Login, Ask, Voice (lazy: LiveKit is most of the bundle), Scribe, Lab, Audit
  demo/            demo-mode responses (mock.js) and the recorded data (fixtures.json)
  styles.css       design tokens (light, dark) and components
```

Screenshots for the docs: `just ui-demo` in one terminal, `just ui-screenshots` (and
`just ui-screenshots dark`) in another; they go to `docs/presentation/ui/`.
