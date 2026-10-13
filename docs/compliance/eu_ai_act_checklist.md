# EU AI Act checklist (high-risk obligations)

Status: portfolio self-assessment, not a conformity assessment · Date: 2026-10-14.
Clinical decision support that influences diagnosis or treatment would likely be high-risk (medical
device software under the MDR, AI Act Annex I). Mapping of the Chapter III, Section 2 requirements:

| Requirement | ClinScribe control | Evidence | Gap |
|---|---|---|---|
| Art. 9 Risk management | Hazard table (SPEC §8), red-team suite, incident drills with postmortems | `evals/reports/redteam/`, `docs/postmortems/` | No formal ISO 14971 process |
| Art. 10 Data governance | Licence-checked public corpus, synthetic patients, golden set with a human-reviewed sample | `data/LICENSES.md`, golden review sheet | Golden review not yet filled in; no subgroup analysis |
| Art. 11 Technical documentation | SPEC, ADRs 0001–0009, evaluation reports | `docs/`, `evals/reports/` | Not in Annex IV format |
| Art. 12 Record-keeping | Hash-chained audit log: actor, role, action, model, prompt version, trace id | `audit_design.md`, `just audit-verify` | Retention not enforced |
| Art. 13 Transparency | Drafts labelled AI-generated; citations on every claim; unsupported statements highlighted | Review UI, `agents/schemas.py` | No instructions-for-use document |
| Art. 14 Human oversight | Doctor approves, edits or rejects every draft; approval bound to exact content; abstains without evidence | `just gate 3`, approval tests | No overseer training material |
| Art. 15 Accuracy, robustness, cybersecurity | Measured quality with confidence intervals; provider failover; injection guardrails; RBAC | `evals/reports/rag/ablation.md`, `just gate 5` | No penetration test; no TLS inside the stack |
| Art. 72 Post-market monitoring | Traces, audit log, nightly evaluation design | SPEC §7 | Nightly job and drift alerts not deployed |
