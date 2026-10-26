# Vendor and subprocessor matrix (HIPAA BAA, GDPR DPA)

Status: portfolio document · Date: 2026-10-14. Vendor terms change: every "verify" entry must be
checked with the vendor before real use. In this build every vendor receives synthetic or public data
only, and model and tracing vendors receive de-identified text only.

| Vendor | Used for | What it receives | Plan here | Position for real PHI |
|---|---|---|---|---|
| Google (Gemini API) | Primary text model; speech-to-speech option (Phase 4) | De-identified text (audio for speech-to-speech) | Free tier | Free-tier terms are not suitable for health data; a paid enterprise offering with a BAA/DPA is needed (verify) |
| Groq | First fallback; evaluation judge | De-identified text | Free tier | Not on the free tier; verify enterprise terms |
| OpenRouter (`:free` models) | Second fallback | De-identified text | Free models | Routes to third-party hosts; not suitable for PHI |
| Ollama (local `llama3.2:3b`) | Last fallback; contextual-retrieval prefixes | De-identified text | Local GPU | No third party |
| Langfuse Cloud (EU) | Traces, prompt versions, scores | De-identified, redacted spans; no message content | Hobby (free) | DPA on paid plans (verify), or self-host |
| Arize Phoenix, self-hosted (optional, ADR-0024) | Traces | The same redacted spans; stays on the machine | Open source, local | None needed (not a processor); switch on its authentication before shared use |
| Deepgram / AssemblyAI | Speech-to-text (Phase 4) | **Raw audio, before de-ID** | Free credit | Must be BAA-covered for real use (verify); alternative: self-hosted Whisper |
| Deepgram (Aura-2) | Text-to-speech, the agent's voice since 2026-10-19 (ADR-0013) | Reply text (de-identified answer) | Free credit | Same vendor and agreement as speech-to-text |
| LiveKit server (self-hosted) | WebRTC media and data between the browser and the voice agent (ADR-0019) | Doctor's audio, de-identified answers and sources | Runs locally (Apache-2.0); not a processor | None needed while self-hosted; LiveKit Cloud would need one |
| Cartesia / ElevenLabs | Text-to-speech (Cartesia until 2026-10-18; ElevenLabs not used) | Reply text | Free tier | Verify enterprise terms, or local TTS |
| GitHub | Source code and CI | Code only (no data, no secrets) | Private repository | Not a processor of patient data |
| Hugging Face Hub | Encoder downloads | Nothing sent (offline at run time) | Public models | Not a processor |

Controls that make the free-tier build acceptable: synthetic data only (CLAUDE.md), de-ID before the
gateway, one gateway for every model call (ADR-0001), redaction before trace export, and `no-log` for
bulk evaluation traffic.
