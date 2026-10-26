"""ClinScribe cascaded voice agent (Phase 4; SPEC section 4), LiveKit Agents 1.8.

Deepgram nova-3-medical streaming STT -> ClinScribe Ask (the API: de-ID, agent graph, retrieval,
cited answer, guardrails) -> Deepgram Aura-2 streaming TTS. The "LLM" of the voice pipeline is the
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
  just voice dev          worker for LiveKit rooms (`just up voice`): the review UI's Voice tab,
                          audio over WebRTC; each cited answer is also sent to the room on the
                          clinscribe.answer topic, so the sources really are on screen
Needs `just up rag` (the API) and DEEPGRAM_API_KEY in .env (speech in and out).
"""

import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any

import httpx
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
    get_job_context,
    llm,
)
from livekit.agents.voice import ModelSettings
from livekit.plugins import deepgram, silero
from livekit.plugins.turn_detector.base import EOUModelBase
from livekit.plugins.turn_detector.english import EnglishModel

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("clinscribe.voice")
API = os.environ.get("CLINSCRIBE_API", "http://127.0.0.1:8000")
# Deepgram Aura-2 (ADR-0013): Cartesia sonic-2 until its free-tier credit ran out on 2026-10-18
VOICE = "aura-2-orpheus-en"
GREETING = "ClinScribe is listening. Ask a clinical question."
NO_IDENTITY = "Voice answers are unavailable: I could not confirm who is asking."
ANSWER_TOPIC = "clinscribe.answer"  # the Voice tab lists each answer's citations from this
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
    def __init__(self, token: str | None = None) -> None:
        super().__init__(
            instructions="ClinScribe answers clinicians' questions from cited guidelines.",
        )
        self._http = httpx.AsyncClient(timeout=120)
        # whose questions these are: in a room, the doctor's delegated token (empty if the API
        # refused: then nothing is asked); in console mode and the tests, the local demo doctor
        self._token = token if token is not None else os.environ.get("CLINSCRIBE_TOKEN", "")
        # one encounter per session: its de-ID mapping is this session's alone and expires with
        # it (config/retention.yaml), instead of one mapping shared by every voice session
        self._encounter = f"voice-{uuid.uuid4().hex[:12]}"
        self.turns: list[dict[str, Any]] = []

    async def llm_node(
        self, chat_ctx: llm.ChatContext, tools: list[llm.Tool], model_settings: ModelSettings
    ) -> AsyncIterable[str]:
        question = ""
        for item in reversed(chat_ctx.items):
            if getattr(item, "role", None) == "user":
                question = item.text_content or ""
                break
        if not self._token:
            yield NO_IDENTITY
            return
        started = time.perf_counter()
        body: dict[str, Any] = {}
        try:
            response = await self._http.post(
                f"{API}/v1/ask",
                json={"encounter_id": self._encounter, "question": question},
                headers={"Authorization": f"Bearer {self._token}"},
            )
            if response.status_code == 200:
                body = response.json()
            else:
                logger.warning("ClinScribe API returned %s", response.status_code)
        except httpx.HTTPError as error:
            logger.warning("ClinScribe API unreachable: %s", type(error).__name__)
        answer = body.get("answer") or {}
        sentences = [] if answer.get("abstained", True) else answer.get("sentences", [])
        await self._show(question, body)
        self.turns.append(
            {
                "ask_ms": (time.perf_counter() - started) * 1000,
                "route": body.get("route"),
                "sentences": len(sentences),
            }
        )
        if not sentences:
            # a word no source uses (a new drug, or a misheard one): say which (ADR-0018)
            unseen = body.get("unseen_terms") or []
            yield f"None of my sources mention {', '.join(unseen)}." if unseen else SAFE
            return
        for sentence in sentences:
            yield re.sub(r"\s*\[\d+\]", "", sentence["text"]) + " "
        yield "Sources are on screen."

    async def _show(self, question: str, body: dict[str, Any]) -> None:
        """The cited answer for the Voice tab, on the room's data channel: sentences with their
        citations and each source's title and link (no source text). Console mode has no room."""
        try:
            room = get_job_context().room
        except RuntimeError:
            return
        answer = body.get("answer") or {}
        payload = {
            "question": question,
            "abstained": answer.get("abstained", True),
            "sentences": answer.get("sentences", []),
            "evidence": [
                {k: e.get(k) for k in ("chunk_id", "title", "section", "source_url")}
                for e in body.get("evidence", [])
            ],
            "unseen_terms": body.get("unseen_terms", []),
        }
        try:
            await room.local_participant.send_text(json.dumps(payload), topic=ANSWER_TOPIC)
        except Exception as error:  # the spoken answer matters more than the screen
            logger.warning("could not send the answer to the room: %s", type(error).__name__)


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
        tts=deepgram.TTS(model=VOICE),
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


async def delegated_token(room: str, user: str) -> str:
    """A short-lived API token for the doctor in this room (ADR-0019), so the audit log records the
    doctor who asked. Empty if the API refuses: the agent then answers nothing rather than asking
    as someone else."""
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.post(
                f"{API}/v1/voice/delegate",
                json={"room": room, "user": user},
                headers={"X-Voice-Agent-Key": os.environ.get("VOICE_AGENT_KEY", "")},
            )
        if response.status_code == 200:
            return str(response.json()["token"])
        logger.warning("voice delegation refused: HTTP %s", response.status_code)
    except httpx.HTTPError as error:
        logger.warning("voice delegation failed: %s", type(error).__name__)
    return ""


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    token = None  # console mode: the local demo doctor (CLINSCRIBE_TOKEN)
    if not ctx.is_fake_job():  # a LiveKit room: act for the doctor who joined it
        doctor = await ctx.wait_for_participant()
        token = await delegated_token(ctx.room.name, doctor.identity)
    session = build_session(os.environ.get("VOICE_TURN", "semantic"))
    await session.start(room=ctx.room, agent=ClinScribeVoice(token))
    await session.say(GREETING if token != "" else NO_IDENTITY)


if __name__ == "__main__":
    load_env()
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
