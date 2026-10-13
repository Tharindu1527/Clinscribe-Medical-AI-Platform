"""Speech-to-speech time to first audio: Gemini Live (Phase 4; ADR-0011).

The same synthetic question audio as the cascaded measurement (data/voice/questions, Cartesia TTS of
golden questions) is streamed at real-time pace to the Gemini Live API (BidiGenerateContent
websocket, model gemini-2.5-flash-native-audio-latest, server-side voice activity detection), then
1 s of silence. TTFA = last audio frame -> first audio chunk of the reply.

What this path cannot do is the point of the comparison: raw audio reaches the provider before any
de-identification, the answer is not grounded in retrieved passages, carries no citations and
passes no guardrail before it is spoken (CLAUDE.md allows this only as a documented exception;
synthetic data only). Calls the provider directly, not through the LiteLLM gateway, which has no
audio-to-audio route; this module is the documented exception.

  uv run --group voice python -m evals.voice.s2s_eval [--n 10]
"""

import argparse
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

import websockets

from config.settings import Settings
from evals.rag.metrics import percentile

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "data" / "voice" / "questions"
REPORT = ROOT / "evals" / "reports" / "voice" / "s2s_latency.md"
MODEL = "models/gemini-2.5-flash-native-audio-latest"
URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
RATE = 16_000


async def turn(audio: bytes) -> float:
    key = Settings().gemini_api_key.get_secret_value()
    async with websockets.connect(URL, additional_headers={"x-goog-api-key": key}) as ws:
        await ws.send(
            json.dumps(
                {
                    "setup": {
                        "model": MODEL,
                        "generationConfig": {"responseModalities": ["AUDIO"]},
                        "systemInstruction": {"parts": [{"text": "Answer the clinician briefly."}]},
                    }
                }
            )
        )
        await asyncio.wait_for(ws.recv(), timeout=30)  # setupComplete
        first_audio = asyncio.get_running_loop().create_future()

        async def receive() -> None:
            async for message in ws:
                data = json.loads(message)
                parts = data.get("serverContent", {}).get("modelTurn", {}).get("parts", [])
                if any("inlineData" in p for p in parts) and not first_audio.done():
                    first_audio.set_result(time.perf_counter())

        reader = asyncio.create_task(receive())
        frame = RATE * 2 // 50
        chunks = [audio[i : i + frame] for i in range(0, len(audio), frame)]
        last = 0.0
        for chunk in [*chunks, *[bytes(frame)] * 50]:  # speech, then 1 s of silence
            await ws.send(
                json.dumps(
                    {
                        "realtimeInput": {
                            "audio": {
                                "data": base64.b64encode(chunk).decode(),
                                "mimeType": f"audio/pcm;rate={RATE}",
                            }
                        }
                    }
                )
            )
            if chunk in chunks[-1:]:
                last = time.perf_counter()
            await asyncio.sleep(0.02)
        try:
            got = await asyncio.wait_for(first_audio, timeout=30)
        finally:
            reader.cancel()
        return float(got - last) * 1000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=10)
    args = parser.parse_args(argv)
    files = sorted(QUESTIONS.glob("*.pcm"))[: args.n + 1]
    results = []
    for n, path in enumerate(files):
        try:
            ms = asyncio.run(turn(path.read_bytes()))
        except (TimeoutError, OSError, websockets.WebSocketException) as exc:
            print(f"{n:2d} failed: {type(exc).__name__}")
            continue
        print(f"{n:2d} ttfa {ms:6.0f} ms" + (" (warm-up)" if n == 0 else ""))
        if n:
            results.append(ms)
    lines = [
        "# Speech-to-speech: Gemini Live time to first audio (Phase 4)",
        "",
        f"{len(results)} turns (+1 warm-up), synthetic question audio streamed at real-time pace;",
        f"model `{MODEL}`, server-side voice activity detection.",
        "",
        "| metric | p50 ms | p95 ms |",
        "|---|---|---|",
        f"| TTFA (last audio frame -> first reply audio) | {percentile(results, 0.5):,.0f} | "
        f"{percentile(results, 0.95):,.0f} |",
        "",
        "Not comparable on quality: these answers are not grounded, cited or guarded (ADR-0011).",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
