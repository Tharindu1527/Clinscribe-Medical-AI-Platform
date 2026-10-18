"""Demo video (SPEC section 14): a scripted run of ClinScribe, recorded from a hidden Chrome.

Every answer, draft and FHIR write in the video is a live call to the running stack. Two things are
not live, and the video says so on screen: the doctor's voice (Cartesia speech streamed into the
live voice steps, because a script cannot speak into a microphone) and the narrator (Cartesia).
Waits longer than 6 s are shown faster than real time, with the real elapsed time on screen.

Scenes: title, architecture, voice question (Deepgram nova-3-medical -> /v1/ask -> Cartesia sonic-2,
the steps of voice/agent_cascaded.py), Ask in the review UI (drug interaction, agentic path), Scribe
(draft, flagged statements, a wrong identifier refused, the approved FHIR write), the audit log as
admin, results, end card.

  just demo-video [--scenes title,results]
Needs `just up rag`, the UI (`npm --prefix apps/web run dev`), DEV_LOGIN=true and ffmpeg on PATH.
Writes .artifacts/demo/clinscribe_demo.mp4 and timeline.json (the measured values of the run).
"""

import argparse
import asyncio
import base64
import contextlib
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import websockets
from playwright.async_api import async_playwright  # type: ignore[import-not-found, unused-ignore]

from apps.api.auth import issue_token
from config.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".artifacts" / "demo"
FRAMES = OUT / "frames"
UI = "http://127.0.0.1:5173"
API = "http://127.0.0.1:8000"
RATE = 24_000  # Cartesia output and Deepgram input, 16-bit mono PCM
CARTESIA = {"Cartesia-Version": "2025-04-16"}
NARRATOR = "5568a7df-e5ab-4442-9fae-2e9ba1b15ad8"  # Cartesia "Quentin - Refined Narrator"
DOCTOR = "25d7abcb-4d6d-4aca-adce-8a1c85620c8b"  # Cartesia "Jessica - Clear Communicator"
AGENT = "47c38ca4-5f35-497b-b1a3-415245fb35e1"  # Cartesia "Daniel", as in voice/agent_cascaded.py
PATIENT = {"id": "1617", "birth_date": "1986-03-18", "family": "Koepp521", "wrong": "Koepp"}
VOICE_QUESTION = "What is the usual starting dose of warfarin?"
ASK_QUESTION = "Does clarithromycin interact with warfarin?"
MAX_REAL_WAIT = 6.0  # longer waits are compressed to SHOWN_WAIT seconds of video
SHOWN_WAIT = 2.5
SCENES = ["title", "architecture", "voice", "ask", "scribe", "audit", "results", "end"]

NARRATION = {
    "title": "This is ClinScribe, a voice-first clinical copilot. It drafts consultation notes, "
    "answers clinical questions with cited evidence, and never writes to the patient record "
    "without a doctor's approval. Everything in this video runs locally, on synthetic and public "
    "data.",
    "architecture": "Speech becomes a transcript, and the transcript is de-identified before any "
    "model sees it. A LangGraph agent retrieves guideline passages and drug facts through MCP "
    "tools. Every model call goes through one LiteLLM gateway with failover, and guardrails check "
    "each answer before the doctor sees it.",
    "voice_intro": "First, voice. A doctor asks a question out loud. The doctor's voice here is "
    "synthetic, because a script made this recording, but every step after it runs live: "
    "Deepgram's medical speech model, ClinScribe's Ask agent, and Cartesia's text to speech.",
    "voice_outro": "The spoken reply is the same de-identified, cited and guardrail-checked answer "
    "that the screen shows. The timings of each stage are on screen. Measured over thirty "
    "questions, time to first audio misses its one and a half second budget, and the cited answer "
    "is the bottleneck.",
    "ask_intro": "The same Ask agent in the review screen. A drug interaction question takes the "
    "agentic path: it grades the retrieved passages, rewrites the query when they are weak, and "
    "adds interaction facts from the DDInter drug graph.",
    "ask_answer": "Every sentence cites a source passage, and the passages can be opened and "
    "checked. When the evidence is missing, the agent abstains instead of guessing.",
    "scribe_intro": "Scribe mode turns a consultation into a SOAP note draft. This consultation is "
    "synthetic, for a synthetic patient loaded into the FHIR server.",
    "scribe_flags": "Each statement links back to the transcript turns it came from. Statements "
    "highlighted in yellow have no guideline source behind them, so they are flagged for the "
    "doctor. Nothing has been saved yet.",
    "scribe_wrong": "To approve, the doctor confirms two patient identifiers. Here the family name "
    "is wrong.",
    "scribe_refused": "So the FHIR server refuses the write, and the refusal is recorded in the "
    "audit log.",
    "scribe_retry": "A new draft, and this time the correct identifiers.",
    "scribe_saved": "The approval token is signed for this exact note and this patient, so the "
    "write goes through. The note is now a FHIR Document Reference.",
    "audit": "An administrator sees the audit trail: the questions, the drafts, the refused write "
    "and the approved one, with the model and prompt version behind each. The rows are "
    "hash-chained, so tampering is detectable.",
    "results": "Every claim is measured. Hybrid search with ColBERT reranking and contextual "
    "chunks lifts recall at ten from 0.81 to 0.91, and answer correctness from 0.76 to 0.91. The "
    "red-team suite passes 63 of 63 cases, the seeded leak test finds no patient data in any trace "
    "or log, and answers keep working with every cloud provider down.",
    "end": "ClinScribe is designed for HIPAA, GDPR and the EU AI Act, not certified for them, and "
    "every result comes from synthetic and public data. Thanks for watching.",
}

# Overlay helpers injected into every document (cards, subtitles, timer, click ring)
OVERLAY_JS = r"""
window.demo = (() => {
  const css = `
#demo-card{position:fixed;inset:0;z-index:99998;display:none;align-items:center;justify-content:center;
  background:#0b1220;color:#e5e7eb;font-family:system-ui,"Segoe UI",sans-serif}
#demo-sub{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);max-width:80%;z-index:99999;
  display:none;background:rgba(0,0,0,.8);color:#fff;font:500 19px/1.4 system-ui,"Segoe UI",sans-serif;
  padding:10px 18px;border-radius:10px;text-align:center}
#demo-timer{position:fixed;top:14px;right:16px;z-index:99999;display:none;background:#1e3a8a;color:#fff;
  font:600 15px system-ui,"Segoe UI",sans-serif;padding:6px 12px;border-radius:999px}
.demo-ring{position:fixed;width:44px;height:44px;border:3px solid #60a5fa;border-radius:50%;
  z-index:99999;pointer-events:none;animation:demo-ring .7s ease-out forwards}
@keyframes demo-ring{from{transform:scale(.4);opacity:1}to{transform:scale(1.5);opacity:0}}
body{padding-bottom:300px !important}
.dc{max-width:1120px;padding:40px;margin-bottom:120px}
.dc h1{font-size:64px;margin:0 0 8px;color:#fff}
.dc h2{font-size:34px;margin:0 0 6px;color:#fff}
.dc .tag{font-size:25px;color:#93c5fd;margin:0 0 26px}
.dc .chips span{display:inline-block;margin:0 10px 10px 0;padding:8px 16px;border-radius:999px;
  background:#1e293b;border:1px solid #334155;font-size:19px}
.dc .foot{margin-top:34px;color:#94a3b8;font-size:17px;line-height:1.5}
.flow{display:flex;gap:10px;align-items:stretch;margin:24px 0}
.flow div{flex:1;background:#111827;border:1px solid #334155;border-radius:12px;padding:14px;
  font-size:16px;line-height:1.4}
.flow div b{display:block;color:#93c5fd;font-size:18px;margin-bottom:6px}
.flow .arrow{flex:0 0 auto;background:none;border:none;align-self:center;font-size:26px;
  color:#64748b;padding:0}
.bar{background:#0f172a;border:1px dashed #475569;border-radius:12px;padding:12px 16px;
  color:#cbd5e1;font-size:16px}
.res{list-style:none;padding:0;margin:18px 0 0;font-size:21px;line-height:1.45}
.res li{margin:12px 0;padding-left:24px;position:relative}
.res li:before{content:"";position:absolute;left:0;top:11px;width:11px;height:11px;border-radius:50%;
  background:#22c55e}
.res li.miss:before{background:#f59e0b}
.res b{color:#fff}
.vrow{display:flex;gap:16px;margin:14px 0;align-items:flex-start}
.vwho{flex:0 0 170px;font-weight:600;font-size:18px;color:#93c5fd}
.vwho small{display:block;font-weight:400;color:#94a3b8;font-size:14px}
.vbox{flex:1;background:#111827;border:1px solid #334155;border-radius:12px;padding:12px 16px;
  font-size:19px;line-height:1.45;min-height:27px}
.vbox .muted,.muted{color:#94a3b8}
.vbox .cite{color:#93c5fd;font-size:15px;margin-left:4px}
.vbox ol{margin:8px 0 0;padding-left:22px;font-size:15px;color:#cbd5e1}
.bars{display:inline-flex;gap:4px;align-items:flex-end;height:22px;vertical-align:middle;margin-right:10px}
.bars i{width:5px;height:5px;background:#60a5fa;border-radius:2px;animation:demo-eq .9s ease-in-out infinite}
.bars i:nth-child(2){animation-delay:.15s}.bars i:nth-child(3){animation-delay:.3s}
.bars i:nth-child(4){animation-delay:.45s}.bars i:nth-child(5){animation-delay:.6s}
@keyframes demo-eq{0%,100%{height:5px}50%{height:22px}}
.vm{margin-top:16px;border-collapse:collapse;font-size:17px}
.vm td{padding:4px 22px 4px 0}
.vm td:last-child{text-align:right;font-variant-numeric:tabular-nums;color:#fff}
.vm tr.total td{border-top:1px solid #334155;font-weight:700;padding-top:8px}`;
  function ensure(id) {
    if (!document.getElementById("demo-style")) {
      const style = document.createElement("style");
      style.id = "demo-style"; style.textContent = css; document.head.appendChild(style);
    }
    let el = document.getElementById(id);
    if (!el) { el = document.createElement("div"); el.id = id; document.body.appendChild(el); }
    return el;
  }
  let timers = [];
  let tick = null;
  return {
    card(markup) { const el = ensure("demo-card"); el.innerHTML = markup; el.style.display = "flex"; },
    uncard() { ensure("demo-card").style.display = "none"; },
    set(id, markup) { const el = document.getElementById(id); if (el) el.innerHTML = markup; },
    subtitle(parts) {
      timers.forEach(clearTimeout); timers = [];
      const el = ensure("demo-sub"); let at = 0;
      for (const [text, ms] of parts) {
        timers.push(setTimeout(() => { el.textContent = text; el.style.display = "block"; }, at));
        at += ms;
      }
      timers.push(setTimeout(() => { el.style.display = "none"; }, at));
    },
    timer(label) {
      const el = ensure("demo-timer"); const start = performance.now(); el.style.display = "block";
      clearInterval(tick);
      const show = () => {
        const s = (performance.now() - start) / 1000;
        el.textContent = `${label} · real time ${s.toFixed(1)} s` + (s > 6 ? " · shown faster" : "");
      };
      show(); tick = setInterval(show, 100);
    },
    stopTimer() { clearInterval(tick); ensure("demo-timer").style.display = "none"; },
    ring(x, y) {
      ensure("demo-sub");
      const el = document.createElement("div"); el.className = "demo-ring";
      el.style.left = `${x - 22}px`; el.style.top = `${y - 22}px`;
      document.body.appendChild(el); setTimeout(() => el.remove(), 700);
    },
  };
})();
"""  # noqa: E501

TITLE_CARD = """<div class="dc"><h1>ClinScribe</h1>
<p class="tag">A voice-first clinical copilot: cited answers, human-approved writes</p>
<div class="chips"><span>Scribe: consultation → SOAP draft → FHIR</span>
<span>Ask: spoken question → cited answer</span><span>Lab: report PDF → flagged Observations</span></div>
<p class="foot">Synthetic and public data only · recorded by a script against the running stack ·
narrator and doctor voices are synthetic (Cartesia)</p></div>"""  # noqa: E501

ARCHITECTURE_CARD = """<div class="dc"><h2>How a question is answered</h2>
<div class="flow">
<div><b>Voice</b>LiveKit Agents · Deepgram nova-3-medical · Cartesia sonic-2</div><div class="arrow">→</div>
<div><b>De-identification</b>Presidio + rules: identifiers become surrogates before any model</div>
<div class="arrow">→</div>
<div><b>Agent (LangGraph)</b>router · fast or agentic retrieval · guardrails · doctor-approval interrupt</div>
<div class="arrow">→</div>
<div><b>Tools (MCP)</b>guidelines: Qdrant + BM25 + ColBERT · drug graph: Neo4j DDInter · FHIR: HAPI</div>
<div class="arrow">→</div>
<div><b>LiteLLM gateway</b>Gemini Flash → Groq → OpenRouter → local Ollama</div></div>
<div class="bar">OpenTelemetry traces with PHI redaction · hash-chained audit log ·
an approval token signed for the exact content of every clinical write</div></div>"""  # noqa: E501

VOICE_CARD = """<div class="dc" style="width:1120px"><h2>Voice · cascaded pipeline</h2>
<p class="muted" style="margin:0 0 10px">The steps of the LiveKit agent, run live; the doctor's voice is
synthetic (Cartesia), streamed in by the recording script</p>
<div class="vrow"><div class="vwho">Doctor<small>synthetic voice</small></div>
<div class="vbox" id="vp-q"><span class="muted">…</span></div></div>
<div class="vrow"><div class="vwho">Transcript<small>Deepgram nova-3-medical</small></div>
<div class="vbox" id="vp-t"><span class="muted">listening</span></div></div>
<div class="vrow"><div class="vwho">ClinScribe<small>/v1/ask: de-ID, retrieval, citations, guardrails</small></div>
<div class="vbox" id="vp-a"><span class="muted">waiting for the question</span></div></div>
<div class="vrow"><div class="vwho">Speech<small>Cartesia sonic-2</small></div>
<div class="vbox" id="vp-s"><span class="muted">—</span></div></div>
<table class="vm" id="vp-m"></table></div>"""  # noqa: E501

RESULTS_CARD = """<div class="dc"><h2>Measured results <span class="muted" style="font-size:20px">
(evals/reports/, synthetic and public data, one laptop)</span></h2><ul class="res">
<li>Retrieval recall@10 0.81 → <b>0.91</b> (hybrid + ColBERT + contextual chunks; 95% CI excludes 0)</li>
<li>Cited-answer correctness 0.76 → <b>0.91</b>; faithfulness unchanged (0.94)</li>
<li>Red-team suite <b>63 / 63</b>: unsourced doses, diagnosis wording, injections, unapproved writes</li>
<li>Seeded PHI leak test: <b>0</b> values in 6 sinks (traces, logs, Langfuse, spend logs, audit)</li>
<li>Turns succeed with <b>every cloud provider down</b> (local Ollama fallback)</li>
<li class="miss">Voice time to first audio p50 3.5 s / p95 19.7 s vs a 1.5 s budget: <b>not met</b>
(the cited answer is the bottleneck)</li></ul></div>"""  # noqa: E501

END_CARD = """<div class="dc"><h1>ClinScribe</h1>
<p class="tag">Voice AI · agents · advanced RAG · LLMOps · healthcare compliance</p>
<p class="foot">Designed for HIPAA, GDPR and the EU AI Act; not certified. Synthetic and public data
only.<br>Results: evals/reports/ · decisions: docs/adr/ · compliance pack: docs/compliance/</p></div>"""  # noqa: E501

BARS = '<span class="bars"><i></i><i></i><i></i><i></i><i></i></span>'


def synthesize(text: str, voice: str, client: httpx.Client) -> bytes:
    """Cartesia sonic-2 speech as 24 kHz PCM, cached by voice and text (reruns cost nothing)."""
    path = OUT / "tts" / f"{hashlib.sha256(f'{voice}|{text}'.encode()).hexdigest()[:20]}.pcm"
    if path.exists():
        return path.read_bytes()
    response = client.post(
        "https://api.cartesia.ai/tts/bytes",
        json=_tts_body(text, voice),
        headers=_cartesia_headers(),
        timeout=120,
    )
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return response.content


def _tts_body(text: str, voice: str) -> dict[str, Any]:
    return {
        "model_id": "sonic-2",
        "transcript": text,
        "voice": {"mode": "id", "id": voice},
        "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": RATE},
        "language": "en",
    }


def _cartesia_headers() -> dict[str, str]:
    return {"X-API-Key": Settings().cartesia_api_key.get_secret_value(), **CARTESIA}


async def speak_live(text: str, client: httpx.AsyncClient) -> tuple[bytes, float]:
    """The agent's spoken answer, streamed: the audio and the wall time of its first byte."""
    audio = bytearray()
    first = 0.0
    async with client.stream(
        "POST",
        "https://api.cartesia.ai/tts/bytes",
        json=_tts_body(text, AGENT),
        headers=_cartesia_headers(),
        timeout=60,
    ) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            if chunk and not first:
                first = time.time()
            audio += chunk
    return bytes(audio), first


async def transcribe_live(
    audio: bytes, started: float, on_text: Callable[[str], Awaitable[None]]
) -> tuple[str, float]:
    """Stream the question to Deepgram at real-time pace from `started`; returns the transcript and
    the wall time of the end-of-utterance result (300 ms endpointing, as in the agent)."""
    key = Settings().deepgram_api_key.get_secret_value()
    url = (
        "wss://api.deepgram.com/v1/listen?model=nova-3-medical&encoding=linear16"
        f"&sample_rate={RATE}&channels=1&endpointing=300&interim_results=true&smart_format=true"
    )
    frame = RATE * 2 // 50  # 20 ms
    parts: list[str] = []
    final_at = 0.0
    sent_all = False
    done = asyncio.Event()
    async with websockets.connect(url, additional_headers={"Authorization": f"Token {key}"}) as ws:

        async def receive() -> None:
            nonlocal final_at
            async for message in ws:
                data = json.loads(message)
                if data.get("type") != "Results":
                    continue
                text = data["channel"]["alternatives"][0]["transcript"]
                if data.get("is_final") and text:
                    parts.append(text)
                interim = [text] if text and not data.get("is_final") else []
                await on_text(" ".join(parts + interim))
                ends = data.get("speech_final") or data.get("from_finalize")
                if ends and sent_all and not done.is_set():
                    final_at = time.time()
                    done.set()

        reader = asyncio.create_task(receive())
        for index, begin in enumerate(range(0, len(audio), frame)):
            await asyncio.sleep(max(0.0, started + index * 0.02 - time.time()))
            await ws.send(audio[begin : begin + frame])
        sent_all = True
        for _ in range(75):  # up to 1.5 s of silence for the endpointing to fire
            if done.is_set():
                break
            await ws.send(bytes(frame))
            await asyncio.sleep(0.02)
        if not done.is_set():
            await ws.send(json.dumps({"type": "Finalize"}))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(done.wait(), timeout=5)
        await ws.send(json.dumps({"type": "CloseStream"}))
        reader.cancel()
    return " ".join(parts), final_at or time.time()


def remap(t: float, t0: float, fast: list[tuple[float, float]]) -> float:
    """Video time of wall time t: each long wait is compressed to SHOWN_WAIT seconds."""
    out = t - t0
    for begin, end in fast:
        length = end - begin
        if t >= end:
            out -= length - SHOWN_WAIT
        elif t > begin:
            out -= (t - begin) * (1 - SHOWN_WAIT / length)
    return out


class Recorder:
    """Screencast frames from Chrome (CDP), the audio clips to place, and the compressed waits."""

    def __init__(self, page: Any, cdp: Any, lines: dict[str, bytes]) -> None:
        self.page = page
        self.cdp = cdp
        self.lines = lines
        self.frames: list[tuple[float, Path]] = []
        self.clips: list[tuple[float, bytes]] = []
        self.fast: list[tuple[float, float]] = []
        self.busy_until = 0.0
        self.measured: dict[str, Any] = {}
        cdp.on("Page.screencastFrame", self._frame)

    async def _frame(self, params: dict[str, Any]) -> None:
        stamp = float(params.get("metadata", {}).get("timestamp") or time.time())
        path = FRAMES / f"{len(self.frames):06d}.jpg"
        path.write_bytes(base64.b64decode(params["data"]))
        self.frames.append((stamp, path))
        with contextlib.suppress(Exception):
            await self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})

    async def screencast(self) -> None:
        options = {"format": "jpeg", "quality": 85, "maxWidth": 1920, "maxHeight": 1080}
        await self.cdp.send("Page.startScreencast", options)

    async def js(self, script: str, arg: Any = None) -> Any:
        return await self.page.evaluate(script, arg)

    async def card(self, markup: str) -> None:
        await self.js("m => demo.card(m)", markup)

    async def set(self, element: str, markup: str) -> None:
        await self.js("([i, m]) => demo.set(i, m)", [element, markup])

    async def settle(self, pause: float = 0.3) -> None:
        """Wait until the narrator has finished (clips never overlap a compressed wait)."""
        await asyncio.sleep(max(0.0, self.busy_until - time.time()) + pause)

    async def narrate(self, key: str) -> None:
        await self.settle()
        pcm = self.lines[key]
        duration = len(pcm) / 2 / RATE
        start = time.time()
        self.clips.append((start, pcm))
        sentences = re.split(r"(?<=[.!?:])\s+", NARRATION[key])
        total = sum(len(s) for s in sentences)
        parts = [[s, int(duration * 1000 * len(s) / total)] for s in sentences]
        await self.js("p => demo.subtitle(p)", parts)
        self.busy_until = start + duration

    async def wait(self, label: str, target: Awaitable[Any]) -> Any:
        """Show a real-time timer from the click that started the wait; compress long waits, but
        never while the narrator is speaking (the audio would no longer match the picture)."""
        start = time.time()
        await self.js("l => demo.timer(l)", label)
        try:
            return await target
        finally:
            end = time.time()
            await self.js("() => demo.stopTimer()")
            begin = max(start + 0.8, self.busy_until + 0.2)
            if end - start > MAX_REAL_WAIT and end - 0.4 - begin > SHOWN_WAIT:
                self.fast.append((begin, end - 0.4))
            self.measured.setdefault("waits", []).append(
                {"label": label, "real_s": round(end - start, 1)}
            )

    async def click(self, locator: Any) -> None:
        await locator.scroll_into_view_if_needed()
        box = await locator.bounding_box()
        if box:
            await self.js(
                "([x, y]) => demo.ring(x, y)", [box["x"] + box["width"] / 2, box["y"] + 18]
            )
            await asyncio.sleep(0.25)
        await locator.click()

    async def type(self, locator: Any, text: str) -> None:
        await self.click(locator)
        await locator.fill("")
        await locator.press_sequentially(text, delay=45)

    async def scroll_to(self, locator: Any, block: str = "center") -> None:
        await locator.evaluate(
            "(el, b) => el.scrollIntoView({behavior: 'smooth', block: b})", block
        )
        await asyncio.sleep(0.9)


async def scene_cards(rec: Recorder, markup: str, key: str) -> None:
    await rec.card(markup)
    await rec.narrate(key)
    await rec.settle(0.8)


async def scene_voice(rec: Recorder, question_pcm: bytes, token: str) -> None:
    await rec.card(VOICE_CARD)
    await rec.narrate("voice_intro")
    await rec.settle(0.6)
    await rec.set("vp-q", f"{BARS}<span class='muted'>speaking</span>")
    started = time.time() + 0.3
    rec.clips.append((started, question_pcm))
    speech_end = started + len(question_pcm) / 2 / RATE

    async def show(text: str) -> None:
        await rec.set("vp-t", html.escape(text) or "<span class='muted'>listening</span>")

    transcript, final_at = await transcribe_live(question_pcm, started, show)
    await rec.set("vp-q", "<span class='muted'>finished speaking</span>")
    await show(transcript)
    await rec.set("vp-a", f"{BARS}<span class='muted'>de-identifying, retrieving, citing</span>")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API}/v1/ask",
            json={"encounter_id": f"demo-voice-{int(time.time())}", "question": transcript},
            headers={"Authorization": f"Bearer {token}"},
            timeout=300,
        )
        response.raise_for_status()
        body = response.json()
        answered_at = time.time()
        evidence = body.get("evidence", [])
        numbers = {item["chunk_id"]: n for n, item in enumerate(evidence, start=1)}
        answer = body.get("answer") or {}
        sentences = [] if answer.get("abstained", True) else answer.get("sentences", [])
        shown = " ".join(
            html.escape(s["text"])
            + "".join(f"<span class='cite'>[{numbers.get(c, '?')}]</span>" for c in s["citations"])
            for s in sentences
        )
        cited = {numbers[c] for s in sentences for c in s["citations"] if c in numbers}
        sources = "".join(
            "<li>{} — {}</li>".format(
                html.escape(evidence[n - 1]["title"]), html.escape(evidence[n - 1]["section"])
            )
            for n in sorted(cited)
        )
        route = f"<div class='muted' style='font-size:14px'>{body.get('route')} path</div>"
        await rec.set(
            "vp-a",
            (shown or "<span class='muted'>no answer with evidence</span>")
            + route
            + (f"<ol>{sources}</ol>" if sources else ""),
        )
        spoken = " ".join(re.sub(r"\s*\[\d+\]", "", s["text"]) for s in sentences)
        spoken = (
            f"{spoken} Sources are on screen." if spoken else "I cannot answer that with evidence."
        )
        await rec.set("vp-s", f"{BARS}<span class='muted'>synthesizing</span>")
        audio, first_byte = await speak_live(spoken, client)
    rec.clips.append((first_byte, audio))
    await rec.set("vp-s", f"{BARS}{html.escape(spoken)}")
    stages = [
        ("End of speech → final transcript (endpointing included)", final_at - speech_end),
        ("Ask: de-ID, retrieval, cited answer, guardrails", answered_at - final_at),
        ("Speech: first audio byte", first_byte - answered_at),
    ]
    rows = "".join(f"<tr><td>{name}</td><td>{ms * 1000:,.0f} ms</td></tr>" for name, ms in stages)
    ttfa = first_byte - speech_end
    rows += (
        f"<tr class='total'><td>Time to first audio (budget 1,500 ms)</td>"
        f"<td>{ttfa * 1000:,.0f} ms</td></tr>"
    )
    await rec.set("vp-m", rows)
    rec.measured["voice"] = {
        "transcript": transcript,
        "route": body.get("route"),
        "sentences": len(sentences),
        **{name: round(ms * 1000) for name, ms in stages},
        "time_to_first_audio_ms": round(ttfa * 1000),
    }
    rec.busy_until = first_byte + len(audio) / 2 / RATE
    await rec.narrate("voice_outro")
    await rec.settle(0.8)


async def sign_in(rec: Recorder, user: str) -> None:
    page = rec.page
    await page.locator("select").wait_for()
    if user != "dr-demo":
        await rec.click(page.locator("select"))
        await page.select_option("select", user)
        await asyncio.sleep(0.5)
    await rec.click(page.locator("button", has_text="Sign in"))
    await page.locator("header").wait_for()


async def scene_ask(rec: Recorder) -> None:
    page = rec.page
    await rec.js("() => demo.uncard()")
    await rec.narrate("ask_intro")
    await sign_in(rec, "dr-demo")
    await rec.type(page.locator("section form textarea"), ASK_QUESTION)
    await rec.settle()
    await rec.click(page.locator("section form button"))
    result = page.locator("p.label:has-text('path'), p.error").first
    await rec.wait("Searching guidelines", result.wait_for(timeout=300_000))
    if await page.locator("p.error").count():
        raise RuntimeError(f"Ask failed: {await page.locator('p.error').inner_text()}")
    rec.measured["ask"] = {"label": await result.inner_text()}
    await rec.scroll_to(result, "start")
    await rec.narrate("ask_answer")
    passage = page.locator("ol.sources details summary").first
    if await passage.count():
        await rec.click(passage)
        await asyncio.sleep(0.5)
        await rec.scroll_to(passage)
    await rec.settle(0.8)


async def create_draft(rec: Recorder) -> Any:
    page = rec.page
    await rec.js("() => window.scrollTo({top: 0, behavior: 'smooth'})")
    await asyncio.sleep(0.8)
    await rec.click(page.locator("section form button"))
    review = page.locator(".review, p.error").first
    await rec.wait("Writing the draft", review.wait_for(timeout=300_000))
    if await page.locator("p.error").count():
        raise RuntimeError(f"Draft failed: {await page.locator('p.error').inner_text()}")
    return review


async def approve(rec: Recorder, family: str) -> str:
    page = rec.page
    await rec.scroll_to(page.locator(".review"))
    await rec.type(page.locator("input[placeholder^='birth date']"), PATIENT["birth_date"])
    await rec.type(page.locator("input[placeholder='family name']"), family)
    await rec.settle()
    await rec.click(page.locator(".review button", has_text="Approve"))
    result = page.locator("p.ok, p.warn, p.error").first
    await rec.wait("Checking the identifiers and writing", result.wait_for(timeout=120_000))
    await rec.scroll_to(result)
    return str(await result.inner_text())


async def scene_scribe(rec: Recorder) -> None:
    page = rec.page
    await rec.click(page.locator("nav button", has_text="scribe"))
    await rec.narrate("scribe_intro")
    await rec.type(page.locator("label:has-text('FHIR patient id') input"), PATIENT["id"])
    await create_draft(rec)
    await rec.scroll_to(page.locator("p.label:has-text('AI-generated draft')"), "start")
    await rec.narrate("scribe_flags")
    statements = page.locator(".statement")
    for index in range(await statements.count()):
        await rec.scroll_to(statements.nth(index))
        await asyncio.sleep(0.3)
    await rec.narrate("scribe_wrong")
    refused = await approve(rec, PATIENT["wrong"])
    if "refused" not in refused:
        raise RuntimeError(f"expected a refused write, got: {refused}")
    await rec.narrate("scribe_refused")
    await rec.narrate("scribe_retry")
    await create_draft(rec)
    saved = await approve(rec, PATIENT["family"])
    if not saved.startswith("Saved to FHIR"):
        raise RuntimeError(f"approved write failed: {saved}")
    rec.measured["scribe"] = {"refused": refused, "saved": saved}
    await rec.narrate("scribe_saved")
    await rec.settle(0.8)


async def scene_audit(rec: Recorder) -> None:
    page = rec.page
    await page.reload()
    with contextlib.suppress(Exception):
        await rec.screencast()  # keep frames coming if Chrome stopped the screencast on reload
    await sign_in(rec, "admin-demo")
    await rec.click(page.locator("button", has_text="Load audit log"))
    await page.locator("table").wait_for()
    await rec.narrate("audit")
    await asyncio.sleep(3)
    await rec.scroll_to(page.locator("table tbody tr").nth(12))
    await rec.settle(0.8)


def assemble(rec: Recorder, stopped: float) -> Path:
    frames = sorted(rec.frames)
    t0 = frames[0][0]
    concat = ["ffconcat version 1.0"]
    following = [t for t, _ in frames[1:]] + [stopped]
    for (stamp, path), nxt in zip(frames, following, strict=True):
        duration = remap(nxt, t0, rec.fast) - remap(stamp, t0, rec.fast)
        if duration > 0:
            concat += [f"file '{path.as_posix()}'", f"duration {duration:.4f}"]
    concat.append(f"file '{frames[-1][1].as_posix()}'")
    (OUT / "frames.ffconcat").write_text("\n".join(concat) + "\n", encoding="utf-8")

    end = remap(stopped, t0, rec.fast)
    track = np.zeros(int((end + 1) * RATE), dtype=np.int32)
    for stamp, pcm in rec.clips:
        begin = max(0, int(remap(stamp, t0, rec.fast) * RATE))
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.int32)
        stop = min(len(track), begin + len(samples))
        track[begin:stop] += samples[: stop - begin]
    with wave.open(str(OUT / "audio.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        headroom = track * 0.89  # -1 dB: Cartesia clips peak at full scale
        out.writeframes(np.clip(headroom, -32768, 32767).astype("<i2").tobytes())

    video = OUT / "clinscribe_demo.mp4"
    video_filter = (
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0b1220,fps=30,format=yuv420p"
    )
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(OUT / "frames.ffconcat"),
        "-i", str(OUT / "audio.wav"),
        "-vf", video_filter, "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(video),
    ]  # fmt: skip
    subprocess.run(command, check=True)
    rec.measured["video_s"] = round(end, 1)
    return video


def preflight() -> None:
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is not on PATH")
    try:
        httpx.get(UI, timeout=5).raise_for_status()
    except httpx.HTTPError:
        raise SystemExit(
            f"review UI not reachable at {UI}: npm --prefix apps/web run dev"
        ) from None
    httpx.get(f"{API}/health", timeout=5).raise_for_status()
    login = httpx.post(f"{API}/v1/dev/login", json={"user": "dr-demo"}, timeout=10)
    if login.status_code != 200:
        raise SystemExit("the UI sign-in needs DEV_LOGIN=true in .env (then restart the API)")


async def record(scenes: list[str]) -> int:
    settings = Settings()
    token = issue_token("dr-demo", settings.auth_token_key)
    preflight()
    with httpx.Client() as client:
        lines = {
            key: synthesize(text, NARRATOR, client)
            for key, text in NARRATION.items()
            if key.split("_")[0] in scenes
        }
        question_pcm = synthesize(VOICE_QUESTION, DOCTOR, client) if "voice" in scenes else b""
    shutil.rmtree(FRAMES, ignore_errors=True)
    FRAMES.mkdir(parents=True)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720}, device_scale_factor=1.5, color_scheme="dark"
        )
        await context.add_init_script(script=OVERLAY_JS)
        page = await context.new_page()
        await page.goto(UI)
        await page.locator("select").wait_for()
        rec = Recorder(page, await context.new_cdp_session(page), lines)
        await rec.card("")
        await rec.screencast()
        await asyncio.sleep(0.5)
        try:
            for scene in scenes:
                if scene == "title":
                    await scene_cards(rec, TITLE_CARD, "title")
                elif scene == "architecture":
                    await scene_cards(rec, ARCHITECTURE_CARD, "architecture")
                elif scene == "voice":
                    await scene_voice(rec, question_pcm, token)
                elif scene == "ask":
                    await scene_ask(rec)
                elif scene == "scribe":
                    await scene_scribe(rec)
                elif scene == "audit":
                    await scene_audit(rec)
                elif scene == "results":
                    await scene_cards(rec, RESULTS_CARD, "results")
                elif scene == "end":
                    await scene_cards(rec, END_CARD, "end")
            await rec.settle(1.0)
        finally:
            stopped = time.time()
            with contextlib.suppress(Exception):
                await rec.cdp.send("Page.stopScreencast")
            await browser.close()
    video = assemble(rec, stopped)
    rec.measured.update({"scenes": scenes, "compressed_waits": len(rec.fast)})
    (OUT / "timeline.json").write_text(json.dumps(rec.measured, indent=2), encoding="utf-8")
    print(f"{video} ({rec.measured['video_s']} s)\n{json.dumps(rec.measured, indent=2)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--scenes",
        default=",".join(SCENES),
        help="comma-separated subset, in order (scribe needs ask first: it signs in)",
    )
    args = parser.parse_args(argv)
    scenes = [s for s in args.scenes.split(",") if s]
    if unknown := set(scenes) - set(SCENES):
        parser.error(f"unknown scenes: {sorted(unknown)}")
    tmp = OUT / "tmp"  # the browser profile and driver temp files stay on D:, not in %TEMP% on C:
    tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = os.environ["TEMP"] = str(tmp)
    return asyncio.run(record(scenes))


if __name__ == "__main__":
    sys.exit(main())
