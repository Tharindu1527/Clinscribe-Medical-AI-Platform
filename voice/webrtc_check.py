"""Browser voice over WebRTC, end to end without a browser (ADR-0019; SPEC section 4).

A Python LiveKit client stands in for the doctor's browser: it asks the API for a room token
(POST /v1/voice/token, as a doctor), joins the room on the self-hosted LiveKit server, waits for
the voice agent worker to join and finish its greeting, then plays recorded questions (the voice
latency evaluation's cached speech, 16 kHz) at real-time pace followed by silence. Per turn it
records time to first audio as the client hears it (end of the question to the first audible
frame of the agent's reply, so the WebRTC hops are included) and the cited answer the agent sends
on the room's data channel. With an admin token (CLINSCRIBE_ADMIN_TOKEN) it also reads the
audit log: every question must be recorded under the doctor in the room (ADR-0019).

  just up voice; just voice start      (the agent worker; another terminal)
  just voice-webrtc [dr-second] [--n 10]   as that synthetic doctor; writes
                                           evals/reports/voice/webrtc.md
Real calls: Deepgram (speech in and out) and the ClinScribe API (models) per question.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from livekit import rtc

ROOT = Path(__file__).resolve().parents[1]
API = os.environ.get("CLINSCRIBE_API", "http://127.0.0.1:8000")
QUESTIONS = ROOT / "data" / "voice" / "questions"
REPORT = ROOT / "evals" / "reports" / "voice" / "webrtc.md"
ANSWER_TOPIC = "clinscribe.answer"
RATE, FRAME = 16_000, 160  # 10 ms frames
LOUD = 300  # mean absolute sample value that counts as the agent speaking
QUIET_S = 1.5  # this much silence after speech = the agent finished


class AgentEar:
    """Times when the agent's audio is audible."""

    def __init__(self) -> None:
        self.loud_at: list[float] = []

    async def listen(self, track: rtc.Track) -> None:
        async for event in rtc.AudioStream(track, sample_rate=48_000, num_channels=1):
            samples = np.frombuffer(event.frame.data, dtype=np.int16)
            if samples.size and float(np.abs(samples).mean()) > LOUD:
                self.loud_at.append(time.perf_counter())

    def first_after(self, t: float) -> float | None:
        return next((x for x in self.loud_at if x > t), None)

    def quiet_since(self, t: float) -> bool:
        last = self.loud_at[-1] if self.loud_at else 0.0
        return last > t and time.perf_counter() - last > QUIET_S


async def play(source: rtc.AudioSource, pcm: bytes, seconds_of_silence: float = 0.0) -> float:
    """Real-time pace; returns the time the last speech frame was handed to WebRTC."""
    silence = bytes(FRAME * 2) * int(seconds_of_silence * 100)
    start, end_of_speech = time.perf_counter(), 0.0
    data = pcm + silence
    for n, offset in enumerate(range(0, len(data) - FRAME * 2 + 1, FRAME * 2)):
        frame = rtc.AudioFrame(data[offset : offset + FRAME * 2], RATE, 1, FRAME)
        await source.capture_frame(frame)
        if offset < len(pcm):
            end_of_speech = time.perf_counter()
        await asyncio.sleep(max(0.0, start + (n + 1) * 0.01 - time.perf_counter()))
    return end_of_speech


def audit_rows(admin: str, limit: int = 200) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {admin}"}
    rows: list[dict[str, Any]] = httpx.get(
        f"{API}/v1/audit?limit={limit}", headers=headers, timeout=30
    ).json()
    return rows


async def run(n: int) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {os.environ['CLINSCRIBE_TOKEN']}"}
    admin = os.environ.get("CLINSCRIBE_ADMIN_TOKEN", "")
    first_seq = int(audit_rows(admin, 1)[0]["seq"]) if admin else 0
    grant = httpx.post(f"{API}/v1/voice/token", headers=headers, timeout=30).json()
    room, ear, answers = rtc.Room(), AgentEar(), []
    tasks: list[asyncio.Task[None]] = []

    @room.on("track_subscribed")
    def _audio(track: rtc.Track, *_: Any) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            task = asyncio.ensure_future(ear.listen(track))
            task.add_done_callback(_report_failure)
            tasks.append(task)

    def _answer(reader: rtc.TextStreamReader, identity: str) -> None:
        async def read() -> None:
            answers.append(json.loads(await reader.read_all()))

        tasks.append(asyncio.ensure_future(read()))

    room.register_text_stream_handler(ANSWER_TOPIC, _answer)
    joined_at = time.perf_counter()
    await room.connect(grant["url"], grant["token"])
    agent_s = None
    for _ in range(600):  # the worker is dispatched to the new room
        if any(
            p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
            for p in room.remote_participants.values()
        ):
            agent_s = time.perf_counter() - joined_at
            break
        await asyncio.sleep(0.1)
    if agent_s is None:
        await room.disconnect()
        raise SystemExit("no agent joined the room: is `just voice start` running?")
    source = rtc.AudioSource(RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("doctor", source)
    options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    await room.local_participant.publish_track(track, options)
    greeting_wait = time.perf_counter()
    while not ear.quiet_since(greeting_wait) and time.perf_counter() - greeting_wait < 30:
        await play(source, b"", 0.2)  # keep the stream alive while the greeting plays
    turns = []
    for path in sorted(QUESTIONS.glob("*.pcm"))[:n]:
        before = len(answers)
        end = await play(source, path.read_bytes())
        while time.perf_counter() - end < 60 and not (
            ear.first_after(end) and ear.quiet_since(ear.first_after(end) or end)
        ):
            await play(source, b"", 0.2)
        first = ear.first_after(end)
        got = answers[before:]  # more than one: the agent took part of the question as a turn
        turns.append(
            {
                "question": " | ".join(a.get("question", "") for a in got),
                "agent_turns": len(got),
                "ttfa_ms": (first - end) * 1000 if first else None,
                "sentences": sum(len(a.get("sentences", [])) for a in got),
                "sources": max((len(a.get("evidence", [])) for a in got), default=0),
            }
        )
        print(json.dumps(turns[-1]), file=sys.stderr)
    await room.disconnect()
    for task in tasks:
        task.cancel()
    audit: dict[str, int] | None = None  # None: no admin token, the audit log was not read
    if admin:
        audit = {}
        for row in audit_rows(admin):
            if int(row["seq"]) > first_seq and row["action"] in ("ask", "voice.delegate"):
                key = f"{row['action']} by {row['actor']}"
                audit[key] = audit.get(key, 0) + 1
    doctor = grant["room"].removeprefix("clinscribe-").rsplit("-", 1)[0]
    return {
        "room": grant["room"],
        "doctor": doctor,
        "agent_join_s": agent_s,
        "turns": turns,
        "audit": audit,
    }


def _report_failure(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception():
        print(f"agent audio listener failed: {task.exception()!r}", file=sys.stderr)


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def report(result: dict[str, Any]) -> str:
    turns = result["turns"]
    whole = [t for t in turns if t["agent_turns"] == 1]  # a split question has no clean timing
    ttfa = [t["ttfa_ms"] for t in whole if t["ttfa_ms"] is not None]
    answered = [t for t in turns if t["sentences"]]
    split = [t for t in turns if t["agent_turns"] > 1]
    lines = [
        "# Browser voice over WebRTC (ADR-0019)",
        "",
        "Generated by `voice/webrtc_check.py`: a Python LiveKit client in the doctor's place, the",
        "self-hosted LiveKit server (`just up voice`), the production agent worker (`just voice",
        "start`: Deepgram nova-3-medical, the ClinScribe API, Deepgram Aura-2). Time to first",
        "audio is measured at the client, so it includes the WebRTC hops in both directions.",
        "",
        f"- room `{result['room']}` (doctor `{result['doctor']}`); agent joined after "
        f"{result['agent_join_s']:.1f} s",
        "- audit rows written during the run: "
        + (
            "not read (no admin token)"
            if result["audit"] is None
            else ", ".join(f"{k}: {v}" for k, v in sorted(result["audit"].items())) or "none"
        ),
        f"- turns: {len(turns)}; answered with citations on the data channel: {len(answered)}"
        f" (sources per answer: {_mean([t['sources'] for t in answered])})",
        f"- questions the agent split into two or more turns (answered a fragment): {len(split)}",
        f"- time to first audio, unsplit questions: p50 {percentile(ttfa, 0.5):.0f} ms, p95 "
        f"{percentile(ttfa, 0.95):.0f} ms (n {len(ttfa)})"
        if ttfa
        else "- no clean reply timing",
        "",
        "| # | question as transcribed (one per agent turn) | time to first audio ms | sentences "
        "| sources |",
        "|---|---|---|---|---|",
    ]
    for n, t in enumerate(turns, 1):
        ms = f"{t['ttfa_ms']:.0f}" if t["ttfa_ms"] is not None and t["agent_turns"] == 1 else "-"
        lines.append(f"| {n} | {t['question'][:90]} | {ms} | {t['sentences']} | {t['sources']} |")
    return "\n".join(lines) + "\n"


def _mean(values: list[int]) -> str:
    return f"{statistics.mean(values):.1f}" if values else "-"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=10)
    args = parser.parse_args(argv)
    result = asyncio.run(run(args.n))
    REPORT.write_text(report(result), encoding="utf-8")
    print(REPORT.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
