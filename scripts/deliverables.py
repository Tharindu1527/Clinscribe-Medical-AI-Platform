"""SPEC section 14 definition of done: each deliverable against the evidence in the repo.

Prints DONE / PENDING per item and exits 1 while anything is pending (used by `just gate 6`).
Evidence is a file that must exist; items that need people or keys (voice, the demo video, a blog
post) stay PENDING until their evidence file is added.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ITEMS: list[tuple[str, str, list[str]]] = [
    (
        "Product",
        "docker compose up starts the full stack",
        ["docker-compose.yml", "tests/integration/test_stack_health.py"],
    ),
    (
        "Product",
        "Scribe, Ask and Lab work end to end",
        ["tests/live/test_clinical_flow.py", "tests/integration/test_lab_api.py"],
    ),
    ("Product", "Doctor review UI (approve, edit, reject)", ["apps/web/src/App.jsx"]),
    (
        "Evidence",
        "Evaluation report: RAG ablations, agents, safety",
        [
            "evals/reports/rag/ablation.md",
            "evals/reports/redteam/redteam.md",
            "evals/reports/agents/note_writer.md",
        ],
    ),
    ("Evidence", "Evaluation report: ASR WER (voice)", ["evals/reports/voice/asr_wer.md"]),
    (
        "Evidence",
        "Latency and load report, p50/p95 per concurrency level",
        ["evals/reports/load/load_test.md"],
    ),
    ("Evidence", "Voice latency per stage (TTFA, turn time)", ["evals/reports/voice/latency.md"]),
    (
        "Evidence",
        "Cost per consultation, by model choice",
        ["evals/reports/llmops/cost_per_consultation.md"],
    ),
    (
        "Evidence",
        "CI with evaluation gates",
        [
            ".github/workflows/ci.yml",
            "tests/unit/test_rag_regression.py",
            "tests/unit/test_ablation.py",
        ],
    ),
    (
        "Documentation",
        "ADR: vector store, orchestrator, reranker, A2A",
        [
            "docs/adr/0007-vector-store.md",
            "docs/adr/0008-orchestrator.md",
            "docs/adr/0006-reranker.md",
            "docs/adr/0009-a2a.md",
        ],
    ),
    (
        "Documentation",
        "ADR: voice framework, speech-to-speech vs cascaded",
        ["docs/adr/0010-voice-framework.md", "docs/adr/0011-s2s-vs-cascaded.md"],
    ),
    (
        "Documentation",
        "Three incident postmortems",
        [
            "docs/postmortems/0001-provider-outage.md",
            "docs/postmortems/0002-retrieval-drift.md",
            "docs/postmortems/0003-latency-spike.md",
        ],
    ),
    (
        "Documentation",
        "Compliance pack: DPIA, BAA matrix, AI Act checklist, audit design",
        [
            "docs/compliance/dpia.md",
            "docs/compliance/baa_vendor_matrix.md",
            "docs/compliance/eu_ai_act_checklist.md",
            "docs/compliance/audit_design.md",
        ],
    ),
    (
        "Documentation",
        "Runbooks and a contributor guide",
        ["docs/runbooks/local-setup.md", "docs/runbooks/operations.md", "CONTRIBUTING.md"],
    ),
    (
        "Presentation",
        "Demo video of a live voice consultation",
        ["docs/presentation/demo_video.md"],
    ),
    ("Presentation", "README with results, limitations and a JEPA note", ["README.md"]),
    (
        "Presentation",
        "Blog post or LinkedIn write-up (draft written; publishing is yours)",
        ["docs/presentation/write_up.md"],
    ),
]


def main() -> int:
    pending = 0
    for group, item, evidence in ITEMS:
        missing = [e for e in evidence if not (ROOT / e).exists()]
        status = "DONE" if not missing else "PENDING"
        pending += bool(missing)
        print(
            f"[{status:7}] {group}: {item}"
            + (f"  (missing: {', '.join(missing)})" if missing else "")
        )
    print(f"\n{len(ITEMS) - pending} of {len(ITEMS)} deliverables done")
    return 1 if pending else 0


if __name__ == "__main__":
    sys.exit(main())
