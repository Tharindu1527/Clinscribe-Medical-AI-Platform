"""ClinScribe cascaded voice agent (Phase 4; SPEC section 4), LiveKit Agents 1.8.

Deepgram nova-3-medical streaming STT -> ClinScribe Ask (the API: de-ID, agent graph, retrieval,
cited answer, guardrails) -> Cartesia sonic-2 streaming TTS. The "LLM" of the voice pipeline is the
ClinScribe API, so no model sees text that has not been de-identified, and the spoken answer is the
guarded, cited one; citations are spoken as "sources are on screen" and listed by the UI.

- Turn detection: VOICE_TURN=semantic (LiveKit's English end-of-turn model, default) or vad
  (Silero silence only). Both are built; SPEC asks to compare false cut-offs (ADR-0011 notes).
- Barge-in: interruptions on, detected locally (VAD mode, no cloud service); when the doctor talks
  over the agent, TTS stops and the reply is cut to what was played (LiveKit's history truncation).
- Echo cancellation, noise suppression and auto gain run on the microphone before the agent hears
  it: in console mode LiveKit's console applies WebRTC's audio processing module itself; in a
  browser, WebRTC does. Measured in voice/turn_eval.py (evals/reports/voice/turn_taking.md).

  just voice              console mode: local microphone and speakers, no LiveKit server needed
  uv run --project voice python voice/agent_cascaded.py dev    (worker for a LiveKit room)
Needs `just up rag` (the API) and DEEPGRAM_API_KEY / CARTESIA_API_KEY in .env.
"""

import logging
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
from livekit.plugins.turn_detector.base import EOUModelBase
from livekit.plugins.turn_detector.english import EnglishModel

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("clinscribe.voice")
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


class AskApi(llm.LLM):
    """Placeholder session LLM. LiveKit 1.8 drops every user turn when the session has no LLM
    (agent_activity: "skip response if no llm is set"); the answer itself comes from
    ClinScribeVoice.llm_node, which calls the ClinScribe API, so chat() is never used."""

    @property
    def model(self) -> str:
        return "clinscribe-ask"

    @property
    def provider(self) -> str:
        return "clinscribe-api"

    def chat(self, **kwargs: Any) -> llm.LLMStream:
        raise NotImplementedError("answers come from ClinScribeVoice.llm_node (/v1/ask)")


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
        body: dict[str, Any] = {}
        try:
            response = await self._http.post(
                f"{API}/v1/ask",
                json={"encounter_id": "voice-session", "question": question},
                headers={"Authorization": f"Bearer {os.environ.get('CLINSCRIBE_TOKEN', '')}"},
            )
            if response.status_code == 200:
                body = response.json()
            else:
                logger.warning("ClinScribe API returned %s", response.status_code)
        except httpx.HTTPError as error:
            logger.warning("ClinScribe API unreachable: %s", type(error).__name__)
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


def build_session(
    turn: str, inference_executor: Any = None, punctuate: bool = False
) -> AgentSession[Any]:
    """The production session; voice/turn_eval.py measures this same configuration. The
    semantic turn detector runs in the worker's inference process unless one is passed in.
    Transcript punctuation is off (ADR-0012): with it, a question mark on a half-spoken sentence
    made the end-of-turn model cut the doctor off (10 of 36 paused questions vs 1 of 36)."""
    detector: Any = "vad"
    if turn == "semantic" and inference_executor is None:
        detector = EnglishModel()
    elif turn == "semantic":  # EnglishModel's own __init__ insists on a job context
        detector = EnglishModel.__new__(EnglishModel)
        EOUModelBase.__init__(detector, model_type="en", inference_executor=inference_executor)
    return AgentSession(
        stt=deepgram.STT(model="nova-3-medical", endpointing_ms=300, punctuate=punctuate),
        vad=silero.VAD.load(min_silence_duration=0.55),
        llm=AskApi(),
        tts=cartesia.TTS(model="sonic-2", voice=VOICE),
        turn_handling={
            "turn_detection": detector,
            # barge-in detected locally from voice activity; LiveKit's default "adaptive" mode
            # streams audio to LiveKit Cloud (another vendor; failed with 401 here, no account)
            "interruption": {"enabled": True, "mode": "vad"},
            # off: each preemptive attempt would be a full /v1/ask (model calls, an audit row)
            # on a transcript that may still change, up to 3 per turn
            "preemptive_generation": {"enabled": False},
        },
    )


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    session = build_session(os.environ.get("VOICE_TURN", "semantic"))
    await session.start(room=ctx.room, agent=ClinScribeVoice())
    await session.say("ClinScribe is listening. Ask a clinical question.")


if __name__ == "__main__":
    load_env()
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
