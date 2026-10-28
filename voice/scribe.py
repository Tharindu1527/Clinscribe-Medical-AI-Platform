"""Ambient Scribe listener (SPEC section 4): consultation audio -> diarized transcript -> draft.

Scribe mode listens and never speaks. Audio from the microphone, or a WAV file for tests and the
demo, streams to Deepgram nova-3-medical live with speaker diarization. Finished words are grouped
into turns by speaker, speakers are mapped to doctor and patient, and the transcript goes to the
ClinScribe API (`POST /v1/scribe/drafts`), which de-identifies every turn before the note writer
sees it. The draft then waits in the review UI (Scribe tab, "Drafts awaiting review").

- Roles: the first main speaker to say a full sentence (3+ words) is the doctor, as consultations
  open with the clinician; other main speakers are the patient side; fragments that diarization
  splits off (under 5% of the words) are "unknown". Measured on PriMock57 in
  evals/voice/scribe_eval.py.
- A dropped connection ends the session with an error and nothing is drafted: reconnecting is not
  done because Deepgram numbers speakers per connection, so roles could swap. Seen on this PC's
  network about once in ten long file streams; a recorded file can simply be run again.
- Words recognised with a confidence under UNSURE_BELOW go with their turn, and the review screen
  shows them on the statements that use them (ADR-0027; the threshold is chosen in
  evals/voice/asr_confidence.py).
- Live diarization needs real voices: two synthetic TTS voices were not told apart (tried for the
  demo), so the demo plays a PriMock57 consultation instead.
- The speech vendor hears raw audio before de-identification (SPEC section 8: a BAA-covered vendor
  or a self-hosted recogniser in real use). The transcript is printed to this terminal (the doctor's
  own screen) and is not logged.

  just scribe 1617                        microphone; press Enter to finish
  just scribe 1617 --file consult.wav     a recorded consultation (16 kHz WAV), at real-time pace
"""

import argparse
import asyncio
import contextlib
import json
import re
import sys
import time
import uuid
import wave
from collections import Counter
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import websockets

from apps.api.auth import issue_token
from config.settings import Settings

RATE = 16_000
FRAME_S = 0.02
API = "http://127.0.0.1:8000"
MAX_TURN_CHARS = 4000  # the API's limit per turn
DRAIN_S = 300  # longest wait for the last results after the audio ends
MINOR_SHARE = 0.05  # a "speaker" with fewer words than this share is a diarization fragment
UNSURE_BELOW = 0.65  # word confidence under which the doctor is shown the word (ADR-0027)
# numerals: live nova-3-medical wrote "five hundred milligrams" even with smart_format, and the dose
# guardrail matches digits ("500 mg" in the note against the transcript turn)
LISTEN = (
    "wss://api.deepgram.com/v1/listen?model=nova-3-medical&encoding=linear16"
    f"&sample_rate={RATE}&channels=1&diarize=true&smart_format=true&numerals=true"
    "&interim_results=false"
)


@dataclass(frozen=True)
class Word:
    text: str  # punctuated
    start: float  # seconds from the start of the stream
    end: float
    speaker: int
    confidence: float = 1.0  # Deepgram's word confidence (caches made before 2026-10-28 lack it)


@dataclass(frozen=True)
class Turn:
    speaker: int
    text: str
    start: float
    end: float
    unsure: tuple[tuple[str, float], ...] = ()  # (word, confidence) under UNSURE_BELOW


def words_from_result(data: dict[str, Any]) -> list[Word]:
    """Words of one final Deepgram live result (interim results are not requested)."""
    if data.get("type") != "Results" or not data.get("is_final"):
        return []
    words = data["channel"]["alternatives"][0].get("words", [])
    return [
        Word(
            text=str(w.get("punctuated_word") or w["word"]),
            start=float(w["start"]),
            end=float(w["end"]),
            speaker=int(w.get("speaker", 0)),
            confidence=float(w.get("confidence", 1.0)),
        )
        for w in words
    ]


def group_turns(words: list[Word]) -> list[Turn]:
    """Consecutive words of the same speaker form one turn."""
    turns: list[Turn] = []
    current: list[Word] = []
    for word in sorted(words, key=lambda w: w.start):
        if current and word.speaker != current[-1].speaker:
            turns.append(_turn(current))
            current = []
        current.append(word)
    if current:
        turns.append(_turn(current))
    return turns


def _turn(words: list[Word]) -> Turn:
    unsure = tuple(
        (bare, w.confidence)
        for w in words
        if w.confidence < UNSURE_BELOW and (bare := re.sub(r"^\W+|\W+$", "", w.text))
    )
    text = " ".join(w.text for w in words)
    return Turn(words[0].speaker, text, words[0].start, words[-1].end, unsure)


def assign_roles(turns: list[Turn], min_share: float = MINOR_SHARE) -> dict[int, str]:
    """Doctor: the first main speaker to say a turn of 3+ words (consultations open with the
    clinician). Main speakers have at least `min_share` of the words; the other main speakers are
    the patient side (a companion included). Smaller "speakers" are diarization fragments (a few
    words split off) and stay "unknown" rather than guessed. min_share=0 is rule v1, which a
    3-word fragment at the start fooled on PriMock57 (evals/reports/voice/scribe_diarization.md)."""
    words: Counter[int] = Counter()
    for turn in turns:
        words[turn.speaker] += len(turn.text.split())
    total = sum(words.values())
    main = {s for s, n in words.items() if n >= min_share * total} or set(words)
    spoken = [t for t in turns if t.speaker in main]
    opening = next((t for t in spoken if len(t.text.split()) >= 3), spoken[0] if spoken else None)
    doctor = opening.speaker if opening else None
    return {s: ("doctor" if s == doctor else "patient") if s in main else "unknown" for s in words}


def split_text(text: str, limit: int = MAX_TURN_CHARS) -> list[str]:
    """Split an over-long turn at sentence ends so each part fits the API's per-turn limit."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        while len(sentence) > limit:  # a run-on without sentence ends
            parts.append(sentence[:limit])
            sentence = sentence[limit:]
        if current and len(current) + 1 + len(sentence) > limit:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def transcript_for_api(turns: list[Turn], roles: dict[int, str]) -> list[dict[str, Any]]:
    """API turns; each part of a split turn carries the unsure words that are in it."""
    out: list[dict[str, Any]] = []
    for turn in turns:
        for part in split_text(turn.text):
            words = set(re.findall(r"\w+", part.lower()))
            unsure = [
                {"word": word, "confidence": round(confidence, 3)}
                for word, confidence in turn.unsure
                if set(re.findall(r"\w+", word.lower())) <= words
            ]
            row: dict[str, Any] = {"speaker": roles.get(turn.speaker, "unknown"), "text": part}
            if unsure:
                row["unsure"] = unsure
            out.append(row)
    return out


def read_wav(path: Path) -> bytes:
    """16-bit PCM at 16 kHz; stereo is mixed down to mono."""
    with wave.open(str(path), "rb") as audio:
        if audio.getframerate() != RATE or audio.getsampwidth() != 2:
            raise SystemExit(f"{path}: need 16-bit PCM at {RATE} Hz")
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
        if audio.getnchannels() > 1:
            samples = samples.reshape(-1, audio.getnchannels()).mean(axis=1).astype("<i2")
    return samples.tobytes()


async def pcm_source(pcm: bytes, speed: float = 1.0) -> AsyncIterator[bytes]:
    """Recorded audio in 20 ms frames at `speed` times real time (absolute schedule, no drift)."""
    frame = int(RATE * FRAME_S) * 2
    started = time.monotonic()
    for index, begin in enumerate(range(0, len(pcm), frame)):
        await asyncio.sleep(max(0.0, started + index * FRAME_S / speed - time.monotonic()))
        yield pcm[begin : begin + frame]


async def mic_source(stop: asyncio.Event) -> AsyncIterator[bytes]:
    """The default microphone, 16 kHz mono, until `stop` is set."""
    # only the live listener needs PortAudio (`uv sync --group voice`)
    import sounddevice as sd  # type: ignore[import-not-found, import-untyped, unused-ignore]

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def callback(data: Any, frames: int, timing: Any, status: Any) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, bytes(data))

    blocksize = int(RATE * FRAME_S)
    with sd.RawInputStream(
        samplerate=RATE, channels=1, dtype="int16", blocksize=blocksize, callback=callback
    ):
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                yield await asyncio.wait_for(queue.get(), timeout=0.5)


async def transcribe(
    source: AsyncIterator[bytes], on_words: Callable[[list[Word]], None] | None = None
) -> list[Word]:
    """Stream audio to Deepgram live and return every final word with its speaker."""
    key = Settings().deepgram_api_key.get_secret_value()
    words: list[Word] = []
    # pings get 60 s: while Deepgram reads a backed-up socket (a file sent faster than real time)
    # its pong can take longer than the 20 s default
    async with websockets.connect(
        LISTEN, additional_headers={"Authorization": f"Token {key}"}, ping_timeout=60
    ) as ws:

        async def receive() -> None:
            async for message in ws:
                new = words_from_result(json.loads(message))
                if new:
                    words.extend(new)
                    if on_words:
                        on_words(new)

        reader = asyncio.create_task(receive())
        async for chunk in source:
            await ws.send(chunk)
        await ws.send(json.dumps({"type": "Finalize"}))
        await ws.send(json.dumps({"type": "CloseStream"}))
        # The server closes after its last result. Its backlog can be minutes when a file was sent
        # faster than real time, so wait for the close: a cut-off here silently dropped the end of
        # the consultation (found in the PriMock57 eval: words stopped at 322 s of 458 s).
        try:
            await asyncio.wait_for(reader, timeout=DRAIN_S)
        except TimeoutError:
            raise RuntimeError(
                f"the transcript did not finish within {DRAIN_S} s; no partial note is drafted"
            ) from None
    return words


def post_draft(
    transcript: list[dict[str, Any]], patient_id: str, token: str, api: str = API
) -> dict[str, Any]:
    response = httpx.post(
        f"{api}/v1/scribe/drafts",
        json={
            "encounter_id": f"scribe-{uuid.uuid4().hex[:12]}",
            "patient_id": patient_id,
            "transcript": transcript,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=300,
    )
    response.raise_for_status()
    draft: dict[str, Any] = response.json()
    return draft


async def listen(args: argparse.Namespace) -> int:
    def show(new: list[Word]) -> None:
        for turn in group_turns(new):
            print(f"  [speaker {turn.speaker}] {turn.text}", flush=True)

    if args.file:
        source = pcm_source(read_wav(Path(args.file)), args.speed)
        print(f"Streaming {args.file} to Deepgram nova-3-medical (diarization on)...")
    else:
        stop = asyncio.Event()
        source = mic_source(stop)
        print("Listening on the default microphone. Press Enter to finish the consultation.")

        async def wait_for_enter() -> None:
            await asyncio.to_thread(sys.stdin.readline)
            stop.set()

        asyncio.get_running_loop().create_task(wait_for_enter())
    words = await transcribe(source, show)
    turns = group_turns(words)
    if not turns:
        print("No speech recognised; no draft created.")
        return 1
    roles = assign_roles(turns)
    transcript = transcript_for_api(turns, roles)
    print(f"\n{len(turns)} turns, speakers {roles}. Writing the draft...")
    token = issue_token(args.user, Settings().auth_token_key)
    draft = post_draft(transcript, args.patient_id, token, args.api)
    statements = draft["draft"]["statements"]
    print(
        f"Draft {draft['draft_id']} for patient {args.patient_id}: {len(statements)} statements, "
        f"{len(draft['unsupported'])} without a guideline source, {len(draft['removed'])} removed "
        "by guardrails.\nReview it in the UI: Scribe tab, Drafts awaiting review."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("patient_id", help="FHIR Patient id the consultation is about")
    parser.add_argument("--file", help="16 kHz WAV instead of the microphone")
    parser.add_argument("--speed", type=float, default=1.0, help="file playback speed")
    parser.add_argument("--user", default="dr-demo", help="synthetic doctor (config/users.yaml)")
    parser.add_argument("--api", default=API)
    return asyncio.run(listen(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
