import { useEffect, useRef, useState } from "react";
import { Room, RoomEvent, Track } from "livekit-client";
import { call } from "./api.js";
import Citations from "./Citations.jsx";

// Browser voice over WebRTC (ADR-0019). The microphone goes, with the browser's echo cancellation,
// noise suppression and gain control, to the self-hosted LiveKit server and the ClinScribe voice
// agent (`just voice dev`). The agent answers aloud and sends each cited answer on the room's
// data channel; this tab lists them, so "sources are on screen" is true.
const ANSWER_TOPIC = "clinscribe.answer";
const TRANSCRIPT_TOPIC = "lk.transcription"; // LiveKit Agents' live transcript

export default function Voice() {
  const [state, setState] = useState("idle"); // idle | connecting | live
  const [error, setError] = useState("");
  const [mic, setMic] = useState("");
  const [agent, setAgent] = useState("");
  const [lines, setLines] = useState([]);
  const [answers, setAnswers] = useState([]);
  const room = useRef(null);
  const speakers = useRef(null);

  useEffect(() => () => { room.current?.disconnect(); }, []);

  async function start() {
    setError(""); setMic(""); setState("connecting");
    try {
      const { url, token } = await call("POST", "/v1/voice/token", {});
      const r = new Room({
        audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      room.current = r;
      r.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Audio) speakers.current?.append(track.attach());
      });
      r.on(RoomEvent.ParticipantConnected, (p) => { if (p.isAgent) setAgent(p.identity); });
      r.on(RoomEvent.ParticipantDisconnected, (p) => { if (p.isAgent) setAgent(""); });
      r.on(RoomEvent.Disconnected, () => { setState("idle"); setAgent(""); });
      r.registerTextStreamHandler(ANSWER_TOPIC, async (reader) => {
        const answer = JSON.parse(await reader.readAll());
        setAnswers((all) => [answer, ...all]);
      });
      r.registerTextStreamHandler(TRANSCRIPT_TOPIC, async (reader, from) => {
        const text = await reader.readAll();
        if (reader.info?.attributes?.["lk.transcription_final"] === "false" || !text.trim()) return;
        setLines((all) => [...all.slice(-20), { who: from.identity, text }]);
      });
      await r.connect(url, token);
      const present = [...r.remoteParticipants.values()].find((p) => p.isAgent);
      if (present) setAgent(present.identity);
      setState("live");
      try {
        await r.localParticipant.setMicrophoneEnabled(true);
      } catch (e) {
        setMic(`Microphone not available (${e.message}); you can still hear the agent.`);
      }
    } catch (e) {
      setError(e.message);
      setState("idle");
    }
  }

  async function stop() {
    await room.current?.disconnect();
    room.current = null;
  }

  return (
    <section>
      <div className="card">
        <p className="label">Voice over WebRTC · spoken answers are the same cited, guarded ones as Ask</p>
        {state === "live"
          ? <button className="secondary" onClick={stop}>End voice session</button>
          : <button onClick={start} disabled={state === "connecting"}>
              {state === "connecting" ? "Connecting…" : "Start voice session"}
            </button>}
        {state === "live" && (
          <p className={agent ? "ok" : "warn"}>
            {agent ? "ClinScribe is in the room: ask a clinical question."
                   : "Connected; waiting for the voice agent (just voice dev)…"}
          </p>
        )}
        {mic && <p className="warn">{mic}</p>}
        {error && <p className="error">{error}</p>}
        <div ref={speakers} hidden />
      </div>
      {lines.length > 0 && (
        <div className="card">
          <h3>Transcript</h3>
          {lines.map((l, i) => <p key={i}><strong>{l.who === agent ? "ClinScribe" : "You"}:</strong> {l.text}</p>)}
        </div>
      )}
      {answers.map((a, i) => (
        <div className="card" key={i}>
          <p className="label">AI-generated · heard: “{a.question}”</p>
          {a.abstained ? (
            <p className="abstain">
              {a.unseen_terms?.length
                ? `No source mentions ${a.unseen_terms.join(", ")}, so there is no answer with evidence.`
                : "No answer with evidence. Review the sources directly."}
            </p>
          ) : (
            a.sentences.map((s, j) => (
              <p key={j}>{s.text} <Citations ids={s.citations} evidence={a.evidence} /></p>
            ))
          )}
          {a.evidence.length > 0 && (
            <ol className="sources">
              {a.evidence.map((e) => (
                <li key={e.chunk_id}>
                  <a href={e.source_url} target="_blank" rel="noreferrer">{e.title}</a> — {e.section}
                </li>
              ))}
            </ol>
          )}
        </div>
      ))}
    </section>
  );
}
