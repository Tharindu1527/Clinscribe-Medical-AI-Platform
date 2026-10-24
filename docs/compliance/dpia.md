# Data Protection Impact Assessment (DPIA) — ClinScribe

Status: portfolio design document, not legal advice · Date: 2026-10-14 · Data: synthetic and public only

ClinScribe is *designed for* GDPR, HIPAA and the EU AI Act; it is not certified (SPEC §8, §15).
This DPIA follows GDPR Art. 35(7): description, necessity and proportionality, risks, measures.

## 1. Processing

| Item | Description |
|---|---|
| Purpose | Draft clinical notes from consultations, answer clinicians' questions with cited evidence, read lab reports into structured results; a doctor approves every clinical write |
| Data subjects | Patients (special-category health data, GDPR Art. 9), clinicians (user ids, actions) |
| Data | Consultation transcripts, patient summaries (age band, sex, conditions, medications, allergies), lab values, approved notes; audit records |
| Recipients | Clinicians; model providers receive **de-identified text only**; tracing (Langfuse Cloud, EU) receives **de-identified, redacted spans only** |
| Storage | Postgres (audit log, encrypted re-identification mapping), HAPI FHIR (clinical record), files on the clinic host |
| In this build | Synthea patients, ACI-Bench dialogues and public guideline text; no real patient data anywhere |

## 2. Necessity and proportionality

- **Minimisation:** the patient-context tool returns the minimum necessary (no name, birth date or
  address; age capped at 90) (`mcp_servers/fhir_mcp`). Transcripts are de-identified before any model
  call (`privacy/deid`) and checked again inside the agent graph (`agents/guardrails.py`).
- **Human decision:** the system drafts and suggests; nothing is written without a doctor's approval
  bound to the exact content (`agents/approval.py`).
- **Transparency:** every draft and answer is labelled AI-generated; answers cite their sources.

## 3. Risks and measures

| Risk | Before (likelihood / severity) | Measures in ClinScribe | Evidence |
|---|---|---|---|
| PHI disclosed to a model provider | High / high | De-ID before the gateway; second structured-PHI check in the graph; the gateway is the only path to models | `evals/reports/privacy/leak_test.md` (0 leaks); red-team PHI cases 8/8 |
| PHI in logs or traces | Medium / high | Redacting span exporter and log filter; collector redaction processor; bulk traffic not traced | Leak test over 6 sinks: 0 leaks |
| Wrong patient's record changed | Medium / high | Two identifiers checked against the record before any write; lab reports whose name or birth date do not match are refused | Red-team write cases 9/9; `tests/integration/test_lab_api.py` |
| Unreviewed AI output in the record | Medium / high | HITL interrupt; approval token for the exact resource with a 10-minute expiry; fhir-mcp re-verifies | `just gate 3` |
| Hallucinated clinical fact | Medium / high | Cite-or-abstain; dose and diagnosis guardrails | Faithfulness ~0.94; red-team 63/63 |
| Unauthorised access | Medium / high | Role-based access (doctor, admin, operator); signed tokens; audit of reads and writes | `tests/integration/test_clinical_api.py` |
| Tampering with the audit trail | Low / high | Append-only, hash-chained audit table; triggers block UPDATE/DELETE/TRUNCATE | `just audit-verify` |
| Re-identification of surrogates | Low / medium | Fernet-encrypted mapping; HMAC lookup; `/reidentify` callable only with a key held by the API and the de-ID service; the API serves originals to doctors only and audits each disclosure (`phi.reidentify`, counts only); models, logs and traces stay surrogate-only (ADR-0015) | `tests/unit/test_reidentify.py`, live flow test, leak test |

## 4. Gaps before any real use

- **Data subject rights:** no erasure or export endpoint yet (GDPR Art. 15–17); retention periods
  are not enforced. The audit log is append-only by design, so erasure needs a documented legal basis
  for keeping audit records and pseudonymised actors.
- **Processors:** the free tiers used here (Gemini, Groq, OpenRouter, Langfuse) are not contracted
  for health data; real use needs contracted processors or local models (`baa_vendor_matrix.md`).
- **Speech:** raw audio reaches the speech vendor before de-ID (Phase 4); needs a BAA-covered vendor
  or self-hosted speech recognition.
- **Security:** no TLS between services (local Docker network), no secrets manager, no penetration
  test, single-host deployment.
- **Clinical validation:** results come from synthetic and public data; a clinical study is needed.

## 5. Outcome

Residual risk is acceptable **for the synthetic portfolio build only**. Real deployment requires the
gaps in §4 closed, a DPO review, prior consultation where required (GDPR Art. 36) and contracts with
every processor.
