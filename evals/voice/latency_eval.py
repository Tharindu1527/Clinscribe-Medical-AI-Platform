"""Cascaded voice latency per stage (Phase 4; SPEC section 4: TTFA and turn time, p50/p95).

For N golden questions, one turn each, measured stage by stage with the production providers:
1. question audio: Cartesia TTS (16 kHz PCM), standing in for the doctor's voice;
2. STT final: the audio is streamed to Deepgram live (nova-3) at real-time pace; latency = from the
   last audio frame to the final transcript (includes Deepgram's 300 ms endpointing, the turn end);
3. Ask: the transcript goes to `/v1/ask` (de-ID, graph, retrieval, cited answer, guardrails); the
   answer is not streamed, so this is the time to the whole answer;
4. TTS first byte: Cartesia streaming synthesis of the answer's first sentence.
TTFA per turn = STT final + Ask + TTS first byte (network included; turn-detection beyond the
endpointing and the WebRTC hop are not in it). Turn time adds the full spoken answer duration.
Each stage is also written as a span-like record (evals/reports/voice/latency_turns.jsonl).

  uv run --group voice python -m evals.voice.latency_eval [--n 30]   (needs `just up rag`)
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import websockets

from apps.api.auth import issue_token
from config.settings import Settings
from evals.golden.golden import load_items
from evals.rag.metrics import percentile

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "evals" / "reports" / "voice"
API = "http://127.0.0.1:8000"
RATE = 16_000
VOICE = "47c38ca4-5f35-497b-b1a3-415245fb35e1"  # Cartesia "Daniel - Modern Assistant"
CARTESIA = {"Cartesia-Version": "2025-04-16"}
SEED = 4


def tts(text: str, client: httpx.Client) -> tuple[bytes, float]:
    """PCM bytes and time to the first byte (ms)."""
    key = Settings().cartesia_api_key.get_secret_value()
    body = {
        "model_id": "sonic-2",
        "transcript": text,
        "voice": {"mode": "id", "id": VOICE},
        "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": RATE},
        "language": "en",
    }
    started = time.perf_counter()
    first = None
    audio = bytearray()
    with client.stream(
        "POST",
        "https://api.cartesia.ai/tts/bytes",
        json=body,
        headers={"X-API-Key": key, **CARTESIA},
        timeout=60,
    ) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            if first is None and chunk:
                first = (time.perf_counter() - started) * 1000
            audio += chunk
    return bytes(audio), first or float("nan")


async def stt(audio: bytes) -> tuple[str, float, bool]:
    """Final transcript, ms from the last audio frame to the end-of-utterance result, and whether
    Deepgram ended the utterance early (a pause inside the question: a false cut-off at 300 ms)."""
    key = Settings().deepgram_api_key.get_secret_value()
    url = (
        "wss://api.deepgram.com/v1/listen?model=nova-3&encoding=linear16"
        f"&sample_rate={RATE}&channels=1&endpointing=300&interim_results=false"
    )
    frame = RATE * 2 // 50  # 20 ms of 16-bit audio
    silence = bytes(frame)  # 20 ms of zeros
    parts: list[str] = []
    early = False
    sent_all = 0.0
    final_at = 0.0
    done = asyncio.Event()
    async with websockets.connect(url, additional_headers={"Authorization": f"Token {key}"}) as ws:

        async def receive() -> None:
            nonlocal early, final_at
            async for message in ws:
                data = json.loads(message)
                if data.get("type") != "Results":
                    continue
                text = data["channel"]["alternatives"][0]["transcript"]
                if data.get("is_final") and text:
                    parts.append(text)
                ends = data.get("speech_final") or data.get("from_finalize")
                if ends and text and not sent_all:
                    early = True  # utterance ended while the question was still being spoken
                elif ends and sent_all and not done.is_set():
                    final_at = time.perf_counter()
                    done.set()

        reader = asyncio.create_task(receive())
        for begin in range(0, len(audio), frame):
            await ws.send(audio[begin : begin + frame])
            await asyncio.sleep(0.02)
        sent_all = time.perf_counter()
        for _ in range(50):  # up to 1 s of silence so endpointing can fire
            if done.is_set():
                break
            await ws.send(silence)
            await asyncio.sleep(0.02)
        if not done.is_set():
            await ws.send(json.dumps({"type": "Finalize"}))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(done.wait(), timeout=5)
        await ws.send(json.dumps({"type": "CloseStream"}))
        reader.cancel()
    latency = (final_at - sent_all) * 1000 if final_at else float("nan")
    return " ".join(parts), latency, early


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=30)
    args = parser.parse_args(argv)
    items = [i for i in load_items() if i.answerable]
    questions = [i.question for i in random.Random(SEED).sample(items, args.n)]
    token = issue_token("dr-demo", Settings().auth_token_key)
    turns: list[dict[str, Any]] = []
    with httpx.Client() as client:
        cache = ROOT / "data" / "voice" / "questions"
        cache.mkdir(parents=True, exist_ok=True)
        warm = [questions[0], *questions]  # first turn is a warm-up, not counted
        for n, question in enumerate(warm):
            wav = cache / f"{hashlib.sha256(question.encode()).hexdigest()[:16]}.pcm"
            if not wav.exists():
                wav.write_bytes(tts(question, client)[0])
            audio = wav.read_bytes()
            try:
                transcript, stt_ms, early = asyncio.run(stt(audio))
            except (OSError, websockets.WebSocketException) as exc:
                print(f"{n:2d} STT failed: {type(exc).__name__}")
                continue
            started = time.perf_counter()
            response = client.post(
                f"{API}/v1/ask",
                json={"encounter_id": f"voice-{n}", "question": transcript or question},
                headers={"Authorization": f"Bearer {token}"},
                timeout=300,
            )
            ask_ms = (time.perf_counter() - started) * 1000
            answer = response.json().get("answer", {}) if response.status_code == 200 else {}
            sentences = [s["text"] for s in answer.get("sentences", [])]
            spoken = sentences[0] if sentences else "I cannot answer this with evidence."
            reply_audio, tts_ms = tts(spoken, client)
            rest_seconds = len(" ".join(sentences[1:]).split()) / 2.5  # ~150 words per minute
            if n == 0:
                continue  # warm-up
            turn = {
                "question": question,
                "transcript": transcript,
                "status": response.status_code,
                "route": response.json().get("route") if response.status_code == 200 else None,
                "stt_final_ms": stt_ms,
                "early_endpoint": early,
                "ask_ms": ask_ms,
                "tts_first_byte_ms": tts_ms,
                "ttfa_ms": stt_ms + ask_ms + tts_ms,
                "turn_ms": stt_ms
                + ask_ms
                + tts_ms
                + 1000 * (len(reply_audio) / (RATE * 2) + rest_seconds),
                "question_words_match": re.sub(r"\W+", " ", transcript.lower()).split()
                == re.sub(r"\W+", " ", question.lower()).split(),
            }
            turns.append(turn)
            print(
                f"{n:2d} stt {stt_ms:5.0f} ask {ask_ms:6.0f} tts {tts_ms:4.0f} "
                f"ttfa {turn['ttfa_ms']:6.0f} {turn['route']} {response.status_code}"
            )
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "latency_turns.jsonl").write_text(
        "".join(json.dumps(t) + "\n" for t in turns), encoding="utf-8"
    )
    ok = [t for t in turns if t["status"] == 200]

    def row(name: str, key: str) -> str:
        values = [t[key] for t in ok if t[key] == t[key]]
        return f"| {name} | {percentile(values, 0.5):,.0f} | {percentile(values, 0.95):,.0f} |"

    lines = [
        "# Cascaded voice latency per stage (Phase 4)",
        "",
        f"{len(ok)} of {len(turns)} turns answered (golden questions, seed {SEED}); production",
        "providers: Deepgram nova-3 streaming (endpointing 300 ms), the ClinScribe Ask graph",
        "(Groq gpt-oss-20b answer, CPU retrieval), Cartesia sonic-2 streaming TTS.",
        "Budget (SPEC §1):TTFA p95 < 1,500 ms, turn time p95 < 2,500 ms.",
        "",
        "| stage | p50 ms | p95 ms |",
        "|---|---|---|",
        row("STT final (last audio frame -> final transcript, incl. endpointing)", "stt_final_ms"),
        row("Ask: de-ID + graph + retrieval + cited answer + guardrails", "ask_ms"),
        row("TTS first byte (first answer sentence)", "tts_first_byte_ms"),
        row("**TTFA** (sum per turn)", "ttfa_ms"),
        row("Turn time (TTFA + spoken answer)", "turn_ms"),
        "",
        f"Transcripts identical to the question text (after normalisation): "
        f"{sum(t['question_words_match'] for t in turns)}/{len(turns)}; agentic route: "
        f"{sum(t['route'] == 'agentic' for t in ok)}/{len(ok)}.",
        "Early end of utterance (Deepgram endpointing at 300 ms fired at a pause inside the",
        f"question: a VAD-style turn end would cut the doctor off here): "
        f"{sum(t['early_endpoint'] for t in turns)}/{len(turns)} questions.",
        "Turn time estimates the spoken answer at ~150 words per minute after the first sentence.",
    ]
    (REPORTS / "latency.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
