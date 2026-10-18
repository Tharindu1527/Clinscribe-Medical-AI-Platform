"""ClinScribe cascaded voice agent (Phase 4; SPEC section 4), LiveKit Agents 1.8.

Deepgram nova-3-medical streaming STT -> ClinScribe Ask (the API: de-ID, agent graph, retrieval,
cited answer, guardrails) -> Cartesia sonic-2 streaming TTS. The "LLM" of the voice pipeline is the
ClinScribe API, so no model sees text that has not been de-identified, and the spoken answer is the
guarded, cited one; citations are spoken as "sources are on screen" and listed by the UI.

- Turn detection: VOICE_TURN=semantic (LiveKit's English end-of-turn model, default) or vad
  (Silero silence only). Both are built; SPEC asks to compare false cut-offs (ADR-0011 notes).
- Barge-in: interruptions on, detected locally (VAD mode, no cloud service); when the doctor talks
  over the agent, TTS stops and the reply is cut to what was played (LiveKit's history truncation).
- Echo cancellation, noise suppression and auto gain come from the client (browser WebRTC or the
  console's audio device); the agent does no AEC itself.

  just voice              console mode: local microphone and speakers, no LiveKit server needed
  uv run --project voice python voice/agent_cascaded.py dev    (worker for a LiveKit room)
Needs `just up rag` (the API) and DEEPGRAM_API_KEY / CARTESIA_API_KEY in .env.
"""

import os
import re
import time
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any

import httpx
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli, llm
from livekit.agents.voice import ModelSettings
from livekit.plugins import cartesia, deepgram, silero
from livekit.plugins.turn_detector.english import EnglishModel

ROOT = Path(__file__).resolve().parents[1]
API = os.environ.get("CLINSCRIBE_API", "http://127.0.0.1:8000")
VOICE = "47c38ca4-5f35-497b-b1a3-415245fb35e1"  # Cartesia "Daniel - Modern Assistant"
# Keyterm boosting was measured and did not help (medical-term errors 18 -> 17 of 200);
# nova-3-medical did (18 -> 12): evals/reports/voice/asr_wer.md. Kept for reference.
KEYTERMS = [
    "warfarin",
    "apixaban",
    "rivaroxaban",
    "dabigatran",
    "metformin",
    "insulin",
    "amlodipine",
    "lisinopril",
    "losartan",
    "salbutamol",
    "budesonide",
    "amoxicillin",
    "clarithromycin",
    "doxycycline",
    "nitrofurantoin",
    "atorvastatin",
    "HbA1c",
    "INR",
    "eGFR",
    "COPD",
]
SAFE = "I cannot answer that with evidence. Please check the sources."


def load_env() -> None:
    """Read the repo's .env without overriding variables already set (keys stay out of logs)."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


class ClinScribeVoice(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="ClinScribe answers clinicians' questions from cited guidelines.",
        )
        self._http = httpx.AsyncClient(timeout=120)
        self.turns: list[dict[str, Any]] = []

    async def llm_node(
        self, chat_ctx: llm.ChatContext, tools: list[llm.Tool], model_settings: ModelSettings
    ) -> AsyncIterable[str]:
        question = ""
        for item in reversed(chat_ctx.items):
            if getattr(item, "role", None) == "user":
                question = item.text_content or ""
                break
        started = time.perf_counter()
        try:
            response = await self._http.post(
                f"{API}/v1/ask",
                json={"encounter_id": "voice-session", "question": question},
                headers={"Authorization": f"Bearer {os.environ['CLINSCRIBE_TOKEN']}"},
            )
            body = response.json() if response.status_code == 200 else {}
        except httpx.HTTPError:
            body = {}
        answer = body.get("answer") or {}
        sentences = [] if answer.get("abstained", True) else answer.get("sentences", [])
        self.turns.append(
            {
                "ask_ms": (time.perf_counter() - started) * 1000,
                "route": body.get("route"),
                "sentences": len(sentences),
            }
        )
        if not sentences:
            yield SAFE
            return
        for sentence in sentences:
            yield re.sub(r"\s*\[\d+\]", "", sentence["text"]) + " "
        yield "Sources are on screen."


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    turn = os.environ.get("VOICE_TURN", "semantic")
    session: AgentSession[Any] = AgentSession(
        stt=deepgram.STT(model="nova-3-medical", endpointing_ms=300),
        vad=silero.VAD.load(min_silence_duration=0.55),
        tts=cartesia.TTS(model="sonic-2", voice=VOICE),
        turn_handling={
            "turn_detection": EnglishModel() if turn == "semantic" else "vad",
            # barge-in detected locally from voice activity; LiveKit's default "adaptive" mode
            # streams audio to LiveKit Cloud (another vendor; failed with 401 here, no account)
            "interruption": {"enabled": True, "mode": "vad"},
        },
    )
    await session.start(room=ctx.room, agent=ClinScribeVoice())
    await session.say("ClinScribe is listening. Ask a clinical question.")


if __name__ == "__main__":
    load_env()
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
