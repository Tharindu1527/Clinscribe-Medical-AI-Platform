// Demo mode (`npm run dev:demo`): answers from responses recorded from the real API on synthetic
// data (fixtures.json: Synthea patients, a synthetic consultation, guideline questions), so the UI
// can be tried without the stack. Nothing is sent anywhere and nothing is saved; identifiers are
// not checked. Re-record with the capture script described in apps/web/README.md.
import fixtures from "./fixtures.json";

const USERS = { "dr-demo": "doctor", "dr-second": "doctor", "admin-demo": "admin", "ops-demo": "operator" };
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const copy = (value) => structuredClone(value);
let written = 0;

function pickAnswer(question) {
  const exact = fixtures.ask.find((a) => a.question.toLowerCase() === question.trim().toLowerCase());
  if (exact) return exact.response;
  const text = question.toLowerCase();
  const [fast, agentic, abstained] = fixtures.ask.map((a) => a.response);
  if (/mazdutide|unknown drug/.test(text)) return abstained;
  if (/interact|together|combin|with /.test(text)) return agentic;
  return fast;
}

export async function demoCall(method, path, body) {
  const [route] = path.split("?");
  if (route === "/v1/dev/login") {
    await wait(250);
    if (!USERS[body.user]) throw new Error("403: unknown user");
    return { token: "demo", role: USERS[body.user] };
  }
  if (route === "/v1/ask") {
    const answer = copy(pickAnswer(body.question));
    await wait(answer.answer.abstained ? 500 : answer.route === "agentic" ? 2600 : 1300);
    return answer;
  }
  if (route === "/v1/drafts" && method === "GET") {
    await wait(300);
    return copy(fixtures.drafts);
  }
  if (route === "/v1/scribe/drafts") {
    await wait(2400);
    return { ...copy(fixtures.draft), draft_id: `draft-demo-${Date.now().toString(16)}` };
  }
  const review = route.match(/^\/v1\/drafts\/([^/]+)\/review$/);
  if (review) {
    await wait(900);
    if (body.decision === "reject") {
      return { draft_id: review[1], result: { status: "rejected", reason: body.reason } };
    }
    written += 1;
    return {
      draft_id: review[1],
      result: { status: "written", resource_type: "DocumentReference", resource_id: `demo-${written}` },
    };
  }
  const draft = route.match(/^\/v1\/drafts\/([^/]+)$/);
  if (draft) {
    await wait(350);
    return { ...copy(fixtures.draft), draft_id: draft[1] };
  }
  if (route === "/v1/lab/parse") {
    await wait(700);
    return { ...copy(fixtures.lab.response), lab_id: `lab-demo-${Date.now().toString(16)}` };
  }
  const confirm = route.match(/^\/v1\/lab\/([^/]+)\/confirm$/);
  if (confirm) {
    await wait(800);
    const n = fixtures.lab.response.observations.length;
    const chosen = body.indexes ?? [...Array(n).keys()];
    return { lab_id: confirm[1], written: chosen.map((i) => `demo-obs-${i + 1}`), refused: [] };
  }
  if (route === "/v1/audit") {
    await wait(300);
    return copy(fixtures.audit);
  }
  if (route === "/v1/voice/token") {
    await wait(200);
    throw new Error("Voice needs the running stack and the voice agent; it is not part of demo mode");
  }
  throw new Error(`404: ${method} ${route} is not in the demo data`);
}

export const demoLab = { patientId: fixtures.lab.patient_id, message: fixtures.lab.hl7_message };
