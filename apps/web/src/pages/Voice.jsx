import { useEffect, useRef, useState } from "react";
import { Room, RoomEvent, Track } from "livekit-client";
import Answer from "../Answer.jsx";
import { call } from "../api.js";
import { Badge, Button, Callout, Empty, Icon, PageHeader } from "../ui.jsx";

// Browser voice over WebRTC (ADR-0019). The microphone goes, with the browser's echo cancellation,
// noise suppression and gain control, to the self-hosted LiveKit server and the ClinScribe voice
// agent (`just voice dev`). The agent answers aloud and sends each cited answer on the room's
// data channel; this page lists them, so "sources are on screen" is true.
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
  const bottom = useRef(null);

  useEffect(() => () => {
    room.current?.disconnect();
  }, []);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [lines]);

  async function start() {
    setError("");
    setMic("");
    setState("connecting");
    try {
      const { url, token } = await call("POST", "/v1/voice/token", {});
      const r = new Room({
        audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      room.current = r;
      r.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Audio) speakers.current?.append(track.attach());
      });
      r.on(RoomEvent.ParticipantConnected, (p) => {
        if (p.isAgent) setAgent(p.identity);
      });
      r.on(RoomEvent.ParticipantDisconnected, (p) => {
        if (p.isAgent) setAgent("");
      });
      r.on(RoomEvent.Disconnected, () => {
        setState("idle");
        setAgent("");
        setMic("");
      });
      r.registerTextStreamHandler(ANSWER_TOPIC, async (reader) => {
        const answer = JSON.parse(await reader.readAll());
        setAnswers((all) => [answer, ...all]);
      });
      r.registerTextStreamHandler(TRANSCRIPT_TOPIC, async (reader, from) => {
        const text = await reader.readAll();
        if (reader.info?.attributes?.["lk.transcription_final"] === "false" || !text.trim()) return;
        setLines((all) => [...all.slice(-30), { who: from.identity, text }]);
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

  const status =
    state === "live" ? (agent ? ["on", "ClinScribe is listening"] : ["wait", "Connected · waiting for the voice agent"]) : state === "connecting" ? ["wait", "Connecting…"] : ["", "Not connected"];

  return (
    <>
      <PageHeader
        title="Voice"
        description="Ask out loud. Spoken answers are the same de-identified, cited and guarded answers as Ask, and their sources appear here as they are spoken."
      />
      <div className="grid-2">
        <div className="stack">
          <div className="card call">
            <div className={`orb ${state === "live" ? "live" : ""}`}>
              <Icon name={state === "live" ? "wave" : "voice"} size={40} strokeWidth={1.7} />
            </div>
            <div className="row" style={{ justifyContent: "center" }}>
              <span className={`status-dot ${status[0]}`} />
              <strong>{status[1]}</strong>
            </div>
            <p className="muted small" style={{ maxWidth: 420 }}>
              Audio goes over WebRTC to the self-hosted LiveKit server, with echo cancellation and noise suppression on.
              Speech recognition is Deepgram nova-3-medical.
            </p>
            {state === "live" ? (
              <Button variant="danger" icon="phone" onClick={stop}>End session</Button>
            ) : (
              <Button icon="voice" busy={state === "connecting"} onClick={start}>
                {state === "connecting" ? "Connecting" : "Start voice session"}
              </Button>
            )}
            {mic && <Callout tone="warn">{mic}</Callout>}
            {error && <Callout tone="danger" title="Voice is not available.">{error}</Callout>}
            <div ref={speakers} hidden />
          </div>
          {answers.length === 0 ? (
            <div className="card">
              <Empty icon="book" title="Answers appear here">
                Each spoken answer arrives with its citations and sources.
              </Empty>
            </div>
          ) : (
            answers.map((a, i) => (
              <Answer
                key={answers.length - i}
                compact
                question={a.question}
                data={{ answer: { abstained: a.abstained, sentences: a.sentences }, evidence: a.evidence, unseen_terms: a.unseen_terms }}
              />
            ))
          )}
        </div>
        <div className="card sticky">
          <div className="card-head">
            <h3>Live transcript</h3>
            <Badge tone="neutral">{lines.length} turns</Badge>
          </div>
          <div className="card-body" style={{ maxHeight: "60vh", overflowY: "auto" }}>
            {lines.length === 0 ? (
              <p className="muted small">What you say and what ClinScribe answers appear here.</p>
            ) : (
              <div className="bubbles">
                {lines.map((l, i) => (
                  <div key={i} className={`bubble ${l.who === agent ? "agent" : "you"}`}>{l.text}</div>
                ))}
                <div ref={bottom} />
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
