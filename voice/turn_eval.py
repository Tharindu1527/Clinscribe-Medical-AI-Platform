"""Turn taking, barge-in and echo on the real LiveKit pipeline (SPEC sections 4 and 11).

The production session (agent_cascaded.build_session: Deepgram nova-3-medical, Silero VAD, the
LiveKit English end-of-turn model or VAD-only turn detection, local barge-in) runs on LiveKit's own
console audio classes; only the sound card is simulated: 100 ms blocks at 24 kHz on a real-time
clock, with the console's WebRTC audio processing (echo cancellation, noise suppression, high-pass,
auto gain) on the same path as in `just voice`. Speech is Deepgram Aura (synthetic, cached).

1. False cut-offs: 12 clinical questions, each spoken whole and with a silence inside the sentence
   (0.7, 1.2, 2.0 s), for VOICE_TURN=semantic and vad. A cut-off is a user turn committed during
   the pause; the end-of-turn delay (speech end -> commit) comes from the whole questions.
2. Barge-in: the agent speaks a long answer and the user says "Sorry, can I stop you there?" 4 s in.
   Stop latency = the user's speech onset -> the agent's audio buffer cleared (the speaker callback
   plays 100 ms blocks, so the sound stops within 100 ms of that). One extra trial interrupts at
   1.5 s, inside LiveKit's AEC warm-up (the first 3 s of agent speech in a session).
3. Self-interruption: the agent's own audio comes back into the microphone one block (100 ms) later
   at -12 and -24 dB, with the console's echo cancellation on and off. A reply cut short with no
   user speech is a self-interruption. The echo path is linear (no room reverberation, no speaker
   distortion), the easy case for echo cancellation.

  just voice-turns [--quick]          (DEEPGRAM_API_KEY in .env; ~25 min)
Writes evals/reports/voice/turn_taking.md and turn_taking.json.
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import multiprocessing as mp
import os
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import agent_cascaded
import httpx
import numpy as np
from livekit import rtc
from livekit.agents import Agent, StopResponse, llm, utils
from livekit.agents.cli._legacy import ConsoleAudioInput, ConsoleAudioOutput
from livekit.agents.inference_runner import _InferenceRunner
from livekit.agents.ipc.inference_proc_executor import InferenceProcExecutor
from turn_metrics import Utterance, classify, percentile, stop_latency

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "voice" / "turn_eval"
REPORTS = ROOT / "evals" / "reports" / "voice"
RATE = 24_000
BLOCK = RATE // 10  # 100 ms, as the console's sound callbacks
FRAME = RATE // 100  # 10 ms, the audio processing module's frame
DOCTOR = "aura-2-thalia-en"  # Deepgram Aura voices (synthetic)
AGENT = "aura-2-apollo-en"
PAUSES = [0.7, 1.2, 2.0]
PARTS = ["cutoffs", "barge", "echo"]
LABELS = {
    "semantic": "semantic, punctuation on",
    "semantic-nopunct": "**semantic, punctuation off (production, ADR-0012)**",
    "vad": "VAD only, punctuation on",
}
GAP = 5.0  # silence after each utterance: more than the 3 s maximum endpointing delay
# each question split where a clinician might stop to think
QUESTIONS = [
    ("What is the usual starting dose of", "metformin in someone with kidney disease?"),
    ("Can I give amoxicillin to a patient who is", "allergic to penicillin?"),
    ("How often should I check the INR after", "starting warfarin?"),
    ("Is there an interaction between clarithromycin and", "simvastatin?"),
    ("What blood pressure target is recommended for", "people with diabetes?"),
    ("Which inhaler should be added when asthma is", "not controlled on a low dose steroid?"),
    ("How long should antibiotics be given for", "an uncomplicated urinary tract infection?"),
    ("Does apixaban need a lower dose in", "older patients with a low body weight?"),
    ("What should I do if a patient on insulin has", "a glucose below four?"),
    ("When should I refer a child with", "a fever and a rash?"),
    ("Can lisinopril be continued during", "pregnancy?"),
    ("What is the first line treatment for", "community acquired pneumonia?"),
]
INTERRUPT = "Sorry, can I stop you there?"
# every session's commits and final transcripts (for the JSON), and the part being measured
TRACE: list[dict[str, Any]] = []
PART = ["cutoffs"]
ANSWER = (
    "Warfarin is usually started at two to five milligrams once a day, and the dose is then "
    "adjusted to the INR. Check the INR every few days at first, then less often once it is "
    "stable. Watch for bleeding, and review other medicines that interact with it, such as some "
    "antibiotics, before you prescribe them together."
)


def speech(text: str, voice: str) -> np.ndarray:
    """Deepgram Aura speech, 24 kHz 16-bit mono, cached by voice and text. (Cartesia, the agent's
    voice, ran out of free-tier credit on 2026-10-18; Aura uses the Deepgram key already in use.)"""
    path = CACHE / f"{hashlib.sha256(f'{voice}|{text}'.encode()).hexdigest()[:20]}.pcm"
    if not path.exists():
        response = httpx.post(
            "https://api.deepgram.com/v1/speak",
            params={
                "model": voice,
                "encoding": "linear16",
                "sample_rate": RATE,
                "container": "none",
            },
            json={"text": text},
            headers={"Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}"},
            timeout=120,
        )
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    return np.frombuffer(path.read_bytes(), dtype="<i2").copy()


def prepare(questions: list[tuple[str, str]]) -> None:
    """Synthesize every clip before any session starts. speech() blocks on HTTP; inside a session
    that froze the event loop for over a minute (36 new clips), which starved the turn model's
    pings (its process was declared crashed) and stopped the simulated microphone."""
    texts = [("Good morning, can you hear me clearly?", DOCTOR), (INTERRUPT, DOCTOR)]
    texts += [(ANSWER, AGENT)]
    for first, second in questions:
        texts += [(f"{first} {second}", DOCTOR), (first, DOCTOR), (second, DOCTOR)]
    for text, voice in texts:
        speech(text, voice)


def alive(executor: Any) -> None:
    """Stop rather than report numbers made without the turn model."""
    if executor.exitcode is not None or executor.killed:
        raise RuntimeError("the turn-detector inference process died; results would be invalid")


def trimmed(pcm: np.ndarray) -> np.ndarray:
    """Speech only: from the first to the last 10 ms frame above -45 dBFS."""
    frames = pcm[: len(pcm) // FRAME * FRAME].reshape(-1, FRAME).astype(np.float64)
    loud = np.nonzero(np.sqrt((frames**2).mean(axis=1)) / 32768 > 10 ** (-45 / 20))[0]
    return pcm[int(loud[0]) * FRAME : (int(loud[-1]) + 1) * FRAME]


def _frame(samples: np.ndarray) -> rtc.AudioFrame:
    return rtc.AudioFrame(
        data=samples.astype(np.int16).tobytes(),
        sample_rate=RATE,
        num_channels=1,
        samples_per_channel=len(samples),
    )


async def frames(pcm: np.ndarray) -> AsyncIterator[rtc.AudioFrame]:
    """Pre-synthesized agent speech for session.say(audio=...), so replays cost nothing."""
    for begin in range(0, len(pcm), BLOCK):
        yield _frame(pcm[begin : begin + BLOCK])


class Speaker(ConsoleAudioOutput):
    """The console's output, recording when the agent's audio is paused or cleared. On a barge-in
    LiveKit first pauses the audio (the sound stops), then clears the answer once the interruption
    is confirmed, or resumes after 2 s if it was a false one (`resume_false_interruption`)."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(loop)
        self.clock = time.monotonic
        self.cleared: list[float] = []
        self.paused_at: list[float] = []

    def clear_buffer(self) -> None:
        self.cleared.append(self.clock())
        super().clear_buffer()

    def pause(self) -> None:
        self.paused_at.append(self.clock())
        super().pause()


class Card:
    """A simulated sound card on the console's audio path: every 100 ms the speaker block is read
    from the console output and given to the audio processing module as the far end, and the
    microphone block (injected speech + echo of the previous speaker block + faint noise) goes
    through the module in 10 ms frames into the console input."""

    def __init__(
        self, inp: ConsoleAudioInput, out: Speaker, *, aec: bool, echo_db: float | None
    ) -> None:
        self.inp, self.out = inp, out
        self.apm = rtc.AudioProcessingModule(
            echo_cancellation=aec,
            noise_suppression=True,
            high_pass_filter=True,
            auto_gain_control=True,
        )
        self.echo = None if echo_db is None else 10 ** (echo_db / 20)
        self.injections: list[tuple[int, np.ndarray]] = []
        self.started = time.monotonic()
        self.speaking: list[bool] = []  # per block: agent audio in the speaker block
        self._last = np.zeros(BLOCK, dtype=np.int16)
        self._noise = np.random.default_rng(7)

    def now(self) -> float:
        return time.monotonic() - self.started

    def inject(self, pcm: np.ndarray, at: float) -> float:
        """Play `pcm` into the microphone from card time `at` (its speech onset, as trimmed)."""
        self.injections.append((int(at * RATE), pcm))
        return at

    async def run(self) -> None:
        self.started = time.monotonic()
        block = 0
        while True:
            await asyncio.sleep(max(0.0, self.started + block * 0.1 - time.monotonic()))
            out = np.zeros((BLOCK, 1), dtype=np.int16)
            self.out.read_into(out, BLOCK)
            far = out[:, 0]
            for k in range(0, BLOCK, FRAME):
                self.apm.process_reverse_stream(_frame(far[k : k + FRAME]))
            mic = self._noise.normal(0.0, 3.0, BLOCK)  # about -80 dBFS
            low, high = block * BLOCK, (block + 1) * BLOCK
            for start, pcm in self.injections:
                a, b = max(low, start), min(high, start + len(pcm))
                if a < b:
                    mic[a - low : b - low] += pcm[a - start : b - start]
            if self.echo is not None:
                mic += self._last.astype(np.float64) * self.echo
            self._last = far.copy()
            with contextlib.suppress(RuntimeError):
                self.apm.set_stream_delay_ms(100)
            samples = np.clip(mic, -32768, 32767).astype(np.int16)
            for k in range(0, BLOCK, FRAME):
                captured = _frame(samples[k : k + FRAME])
                self.apm.process_stream(captured)
                self.inp.push_frame(captured)
            self.speaking.append(bool(np.any(far)))
            block += 1

    async def playing_from(self, block: int, timeout: float = 15.0) -> float:
        """Card time of the first speaker block from `block` on that carries agent audio."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hits = [n for n in range(block, len(self.speaking)) if self.speaking[n]]
            if hits:
                return hits[0] * 0.1
            await asyncio.sleep(0.05)
        raise TimeoutError("the agent's audio never reached the speaker")


class Probe(Agent):
    """Records every committed user turn and never replies."""

    def __init__(self, card: Card, commits: list[tuple[float, str]]) -> None:
        super().__init__(instructions="Measurement only; never replies.")
        self.card, self.commits = card, commits

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        self.commits.append((self.card.now(), new_message.text_content or ""))
        raise StopResponse()


@contextlib.asynccontextmanager
async def running(
    turn: str, executor: Any, *, aec: bool = True, echo_db: float | None = None
) -> AsyncIterator[tuple[Any, Card, Speaker, list[tuple[float, str]]]]:
    loop = asyncio.get_running_loop()
    inp, out = ConsoleAudioInput(loop), Speaker(loop)
    card = Card(inp, out, aec=aec, echo_db=echo_db)
    out.clock = card.now
    commits: list[tuple[float, str]] = []
    # "semantic" and "vad" with transcript punctuation on (as first measured), "semantic-nopunct"
    # with it off: the production setting since ADR-0012
    mode, _, variant = turn.partition("-")
    session = agent_cascaded.build_session(mode, executor, punctuate=variant != "nopunct")
    session.input.audio = inp
    session.output.audio = out
    finals: list[tuple[float, str]] = []

    def transcribed(event: Any) -> None:
        if event.is_final:
            finals.append((card.now(), event.transcript))

    session.on("user_input_transcribed", transcribed)
    task = asyncio.create_task(card.run())
    await session.start(agent=Probe(card, commits))
    try:
        await asyncio.sleep(2.0)  # VAD and the speech stream settle
        yield session, card, out, commits
    finally:
        TRACE.append(
            {
                "part": PART[0],
                "turn": turn,
                "aec": aec,
                "echo_db": echo_db,
                "commits": commits,
                "finals": finals,
            }
        )
        await session.aclose()  # before the card stops: the speech stream needs audio to close
        task.cancel()


async def cutoffs(
    turn: str, executor: Any, questions: list[tuple[str, str]], pauses: list[float]
) -> list[dict[str, Any]]:
    async with running(turn, executor) as (_, card, _, commits):
        planned: list[tuple[Utterance, float]] = []
        # one unscored question first: the turn model's first inference is slow (measured: no
        # commits for the first two utterances of a cold session, then a burst)
        warm = trimmed(speech("Good morning, can you hear me clearly?", DOCTOR))
        card.inject(warm, card.now() + 0.5)
        at = card.now() + 0.5 + len(warm) / RATE + GAP
        for first, second in questions:
            whole = trimmed(speech(f"{first} {second}", DOCTOR))
            planned.append((Utterance(f"{first} {second}", at, at + len(whole) / RATE), 0.0))
            card.inject(whole, at)
            at += len(whole) / RATE + GAP
            a, b = trimmed(speech(first, DOCTOR)), trimmed(speech(second, DOCTOR))
            for pause in pauses:
                pcm = np.concatenate([a, np.zeros(int(pause * RATE), dtype=np.int16), b])
                gap = (at + len(a) / RATE, at + len(a) / RATE + pause)
                planned.append(
                    (Utterance(f"{first} ... {second}", at, at + len(pcm) / RATE, gap), pause)
                )
                card.inject(pcm, at)
                at += len(pcm) / RATE + GAP
        await asyncio.sleep(max(0.0, at - card.now()) + 1.0)
        times = [t for t, _ in commits]
    rows = []
    for n, (utterance, pause) in enumerate(planned):
        window = planned[n + 1][0].start if n + 1 < len(planned) else utterance.end + GAP
        rows.append(
            {
                "turn": turn,
                "text": utterance.text,
                "pause": pause,
                "start": round(utterance.start, 2),
                "end": round(utterance.end, 2),
                **classify(utterance, times, window),
            }
        )
    return rows


async def barge_in(executor: Any, trials: int) -> list[dict[str, Any]]:
    answer, stop = speech(ANSWER, AGENT), trimmed(speech(INTERRUPT, DOCTOR))
    rows = []
    async with running("semantic", executor) as (session, card, out, _):
        for trial in range(trials + 1):
            mark = len(card.speaking)
            handle = session.say(ANSWER, audio=frames(answer), add_to_chat_ctx=False)
            began = await card.playing_from(mark)
            offset = 1.5 if trial == 0 else 4.0  # trial 0: inside the session's AEC warm-up
            onset = card.inject(stop, began + offset)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(handle.wait_for_playout(), timeout=40)
            latency = stop_latency(onset, out.paused_at + out.cleared)  # the sound stops
            cancelled = stop_latency(onset, out.cleared)  # the answer is dropped
            rows.append(
                {
                    "trial": trial,
                    "warm_up": trial == 0,
                    "offset": offset,
                    "interrupted": bool(handle.interrupted),
                    "latency": latency,
                    "cancelled": cancelled,
                }
            )
            print(f"barge-in {rows[-1]}", flush=True)
            await asyncio.sleep(4.0)  # the user's turn ends before the next answer
    return rows


async def echo(executor: Any, aec: bool, echo_db: float, replies: int) -> dict[str, Any]:
    answer = speech(ANSWER, AGENT)
    interrupted = []
    async with running("semantic", executor, aec=aec, echo_db=echo_db) as (session, _, _, commits):
        for reply in range(replies + 1):  # reply 0 spends the session's AEC warm-up
            handle = session.say(ANSWER, audio=frames(answer), add_to_chat_ctx=False)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(handle.wait_for_playout(), timeout=40)
            if reply:
                interrupted.append(bool(handle.interrupted))
            await asyncio.sleep(2.0)
        user_turns = len(commits)
    row = {
        "aec": aec,
        "echo_db": echo_db,
        "replies": len(interrupted),
        "self_interrupted": sum(interrupted),
        "echo_user_turns": user_turns,
    }
    print(f"echo {row}", flush=True)
    return row


def ms(value: float | None) -> str:
    return "-" if value is None or math.isnan(value) else f"{value * 1000:,.0f} ms"


def report(
    cut: list[dict[str, Any]],
    barge: list[dict[str, Any]],
    echoes: list[dict[str, Any]],
    quick: bool,
) -> str:
    lines = [
        "# Turn taking, barge-in and echo (LiveKit pipeline, simulated sound card)",
        "",
        "Generated by `voice/turn_eval.py`" + (" (--quick subset)" if quick else "") + ": the "
        "production session (`agent_cascaded.build_session`) on LiveKit's console audio classes, "
        "with the sound card simulated in real time (100 ms blocks, 24 kHz, the console's WebRTC "
        "audio processing). Speech is synthetic (Deepgram Aura); LiveKit 1.8.3 defaults: "
        "endpointing "
        "0.5-3.0 s, VAD minimum silence 0.55 s, AEC warm-up 3 s.",
        "",
        "## 1. False cut-offs (a turn ended inside a mid-sentence pause)",
        "",
        "| Turn detection | Pause | Cut off | End-of-turn delay p50 / p95 | Missed |",
        "|---|---|---|---|---|",
    ]
    for turn in ("semantic", "vad", "semantic-nopunct"):
        for pause in [0.0, *sorted({r["pause"] for r in cut if r["pause"]})]:
            rows = [r for r in cut if r["turn"] == turn and r["pause"] == pause]
            if not rows:
                continue
            delays = [r["delay"] for r in rows if r["delay"] is not None]
            label = "none (whole question)" if pause == 0 else f"{pause:.1f} s"
            name = LABELS.get(turn, turn)
            cutoff = "-" if pause == 0 else f"{sum(r['cut_off'] for r in rows)} / {len(rows)}"
            delay = (
                f"{ms(percentile(delays, 50))} / {ms(percentile(delays, 95))}"
                if pause == 0
                else "-"
            )
            lines.append(
                f"| {name} | {label} | {cutoff} | {delay} | {sum(r['missed'] for r in rows)} |"
            )
    lines += [
        "",
        "Production uses the semantic model with transcript punctuation off (ADR-0012): with it "
        "on, "
        "Deepgram ended half-spoken sentences with a question mark and the end-of-turn model took "
        "them as finished. Without it the model waits the full 3 s on some whole questions.",
    ]
    measured = [r for r in barge if not r["warm_up"]]
    latencies = [r["latency"] for r in measured if r["latency"] is not None]
    cancels = [r["cancelled"] for r in measured if r.get("cancelled") is not None]
    warm = next((r for r in barge if r["warm_up"]), None)
    lines += [
        "",
        "## 2. Barge-in (the user interrupts the agent 4 s into an answer)",
        "",
        f"- Interrupted: **{sum(r['interrupted'] for r in measured)} of {len(measured)}** answers.",
        "- **Stop latency** (the user's speech onset -> the agent's audio paused, i.e. the sound "
        f"stops): **p50 {ms(percentile(latencies, 50))}, p95 {ms(percentile(latencies, 95))}** "
        "(+ up to 100 ms for the block already playing).",
        "- The answer is dropped (audio cleared) once the interruption is confirmed: "
        f"p50 {ms(percentile(cancels, 50))}, p95 {ms(percentile(cancels, 95))}; until then LiveKit "
        "would resume a false interruption (`resume_false_interruption`, 2 s).",
    ]
    if warm:
        dropped = "dropped" if warm["interrupted"] else "not dropped: the agent carried on"
        lines.append(
            "- Inside the AEC warm-up (the user speaks 1.5 s into the session's first answer): "
            f"audio paused only after {ms(warm['latency'])}, when the 3 s warm-up ended; answer "
            f"{dropped}."
        )
    lines += [
        "",
        "## 3. Self-interruption (the agent's own voice back in the microphone)",
        "",
        "| Echo cancellation | Echo level | Replies cut short | User turns from echo |",
        "|---|---|---|---|",
    ]
    for row in echoes:
        lines.append(
            f"| {'on' if row['aec'] else 'off'} | {row['echo_db']:.0f} dB | "
            f"{row['self_interrupted']} / {row['replies']} | {row['echo_user_turns']} |"
        )
    lines += [
        "",
        "Parts 2 and 3 ran with punctuation on; both depend on voice activity, not on the "
        "transcript. "
        "Notes: synthetic speech and a linear echo path (no reverberation, no loudspeaker "
        "distortion) "
        "are easier than a real room; a real microphone test is still to do. Small n.",
    ]
    return "\n".join(lines) + "\n"


async def amain(quick: bool, turns: list[str], parts: list[str]) -> int:
    executor = InferenceProcExecutor(
        runners=_InferenceRunner.registered_runners,
        initialize_timeout=5 * 60,
        close_timeout=5,
        memory_warn_mb=2000,
        memory_limit_mb=0,
        ping_interval=5,
        ping_timeout=60,
        high_ping_threshold=2.5,
        mp_ctx=mp.get_context("spawn"),
        loop=asyncio.get_running_loop(),
        http_proxy=None,
    )
    await executor.start()
    await executor.initialize()
    async with utils.http_context.open():  # plugins outside a worker need their own HTTP session
        return await measure(executor, quick, turns, parts)


async def measure(executor: Any, quick: bool, turns: list[str], parts: list[str]) -> int:
    # a run of some parts keeps the other parts' results from the last report
    path = REPORTS / "turn_taking.json"
    previous = (
        json.loads(path.read_text(encoding="utf-8")) if parts != PARTS and path.exists() else {}
    )
    questions = QUESTIONS[:3] if quick else QUESTIONS
    pauses = [1.2] if quick else PAUSES
    try:
        cut = previous.get("cut_offs", [])
        barge = previous.get("barge_in", [])
        echoes = previous.get("echo", [])
        if "cutoffs" in parts:
            PART[0] = "cutoffs"
            cut = [r for r in cut if r["turn"] not in turns]
            for turn in turns:
                cut += await cutoffs(turn, executor, questions, pauses)
                alive(executor)
                found = sum(r["cut_off"] for r in cut if r["turn"] == turn)
                print(f"cut-offs {turn}: {found}", flush=True)
        if "barge" in parts:
            PART[0] = "barge"
            barge = await barge_in(executor, 2 if quick else 12)
            alive(executor)
        if "echo" in parts:
            PART[0] = "echo"
            echoes = []
            for aec in (True, False):
                for level in [-12.0] if quick else [-12.0, -24.0]:
                    echoes.append(await echo(executor, aec, level, 1 if quick else 4))
                    alive(executor)
    finally:
        await executor.aclose()
    REPORTS.mkdir(parents=True, exist_ok=True)

    def rerun(x: dict[str, Any]) -> bool:
        part = x.get("part", "cutoffs")
        return part in parts and (part != "cutoffs" or x["turn"] in turns)

    trace = [x for x in previous.get("trace", []) if not rerun(x)]
    data = {
        "cut_offs": cut,
        "barge_in": barge,
        "echo": echoes,
        "quick": quick,
        "trace": trace + TRACE,
    }
    (REPORTS / "turn_taking.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (REPORTS / "turn_taking.md").write_text(report(cut, barge, echoes, quick), encoding="utf-8")
    print(f"wrote {REPORTS / 'turn_taking.md'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true", help="3 questions, 1 pause, few trials")
    parser.add_argument(
        "--turns", default="semantic,vad", help="part 1 modes: semantic, vad, semantic-nopunct"
    )
    parser.add_argument("--parts", default=",".join(PARTS), help="cutoffs, barge, echo")
    parser.add_argument("--report-only", action="store_true", help="rewrite the report from JSON")
    args = parser.parse_args()
    if args.report_only:
        data = json.loads((REPORTS / "turn_taking.json").read_text(encoding="utf-8"))
        text = report(data["cut_offs"], data["barge_in"], data["echo"], data["quick"])
        (REPORTS / "turn_taking.md").write_text(text, encoding="utf-8")
        return 0
    agent_cascaded.load_env()
    prepare(QUESTIONS[:3] if args.quick else QUESTIONS)
    return asyncio.run(amain(args.quick, args.turns.split(","), args.parts.split(",")))


if __name__ == "__main__":
    sys.exit(main())
