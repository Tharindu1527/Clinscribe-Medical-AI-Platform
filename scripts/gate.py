"""Run a phase's exit gate and print one PASS/FAIL table (SPEC section 12).

Usage: uv run python -m scripts.gate 1
Phase 1 gate: (a) gateway answers when the primary fails; (b) the leak test finds 0 PHI in traces
and logs; (c) Synthea patients are queryable from FHIR. Supporting checks: the full test suite with
the stack required, and the audit hash chain.
Needs `just up` and `just fhir-load`; makes real LLM calls.

Phase 2 gate (wording decided 2026-10-13): the chosen pipeline beats dense-only on recall@10 and on
answer correctness, and its faithfulness is not worse by more than 0.05 (evals/rag/ablation.py,
from the stored runs and answer rows; no LLM calls). Supporting checks: the full suite with the
stack and rag profile required, the golden-set validator, the recorded human review of the golden
sample, and the CI retrieval regression fixture. Needs `just up`, `just up rag`, `just fhir-load`.

Phase 3 gate: the red-team suite passes 100% and no FHIR write happens without a valid approval
(tool, graph, stdio and API tests), plus the live end-to-end flow (real model calls).
"""

import os
import subprocess
import sys
import time

CHECKS_BY_PHASE: dict[str, list[tuple[str, list[str]]]] = {
    "1": [
        ("lint", ["uv", "run", "ruff", "check", "."]),
        ("full test suite (stack required)", ["uv", "run", "pytest", "-q"]),
        (
            "(c) Synthea patients queryable from FHIR",
            ["uv", "run", "pytest", "-q", "tests/integration/test_fhir_data.py"],
        ),
        (
            # Cloud fallback only: "a turn completes with every cloud provider disabled" (the local
            # Ollama step) is the Phase 5 exit gate, and loading it here grew the C: page file.
            "(a) gateway answers when the primary fails",
            [
                "uv",
                "run",
                "pytest",
                "-q",
                "-m",
                "live",
                "tests/live/test_gateway_failover.py",
                "-k",
                "not local_model",
            ],
        ),
        (
            "pipeline: answer, audit row, one trace",
            ["uv", "run", "pytest", "-q", "-m", "live", "tests/live/test_pipeline_endpoint.py"],
        ),
        (
            "(b) leak test: 0 PHI in traces and logs",
            ["uv", "run", "python", "-m", "evals.run", "leak"],
        ),
        ("audit hash chain", ["uv", "run", "python", "-m", "scripts.audit_verify"]),
    ],
    "2": [
        ("lint", ["uv", "run", "ruff", "check", "."]),
        ("full test suite (stack and rag required)", ["uv", "run", "pytest", "-q"]),
        ("golden set valid", ["uv", "run", "python", "-m", "evals.golden.golden"]),
        (
            "golden sample reviewed by a human (task 3)",
            ["uv", "run", "python", "-m", "evals.golden.review", "summary"],
        ),
        (
            "CI retrieval regression fixture",
            ["uv", "run", "pytest", "-q", "tests/unit/test_rag_regression.py"],
        ),
        (
            "chosen pipeline vs dense-only: recall@10, correctness, faithfulness",
            ["uv", "run", "python", "-m", "evals.rag.ablation", "--gate"],
        ),
    ],
}
CHECKS_BY_PHASE["3"] = [
    ("lint", ["uv", "run", "ruff", "check", "."]),
    ("full test suite (stack and rag required)", ["uv", "run", "pytest", "-q"]),
    ("red-team suite: 100% of cases pass", ["uv", "run", "python", "-m", "evals.run", "redteam"]),
    (
        "no FHIR write without a valid approval (tool, graph, stdio, API)",
        [
            "uv",
            "run",
            "pytest",
            "-q",
            "tests/unit/test_mcp_servers.py",
            "tests/unit/test_agent_graph.py",
            "tests/unit/test_approval.py",
            "tests/integration/test_mcp_stdio.py",
            "tests/integration/test_clinical_api.py",
        ],
    ),
    (
        "live: cited Ask answer; transcript -> draft -> approval -> FHIR write",
        ["uv", "run", "pytest", "-q", "-m", "live", "tests/live/test_clinical_flow.py"],
    ),
]
CHECKS_BY_PHASE["5"] = [
    ("lint", ["uv", "run", "ruff", "check", "."]),
    ("full test suite (stack and rag required)", ["uv", "run", "pytest", "-q"]),
    (
        "a turn completes with every cloud provider disabled (local Ollama)",
        [
            "uv",
            "run",
            "pytest",
            "-q",
            "-m",
            "live",
            "tests/live/test_gateway_failover.py",
            "-k",
            "every_cloud or local_model",
        ],
    ),
    (
        "lab parser: values, codes, flags, wrong-patient control",
        ["uv", "run", "python", "-m", "evals.lab.lab_eval"],
    ),
    (
        "lab mode through the API (parse -> confirm -> write)",
        ["uv", "run", "pytest", "-q", "tests/integration/test_lab_api.py"],
    ),
]
CHECKS_BY_PHASE["6"] = [
    ("lint", ["uv", "run", "ruff", "check", "."]),
    ("full test suite (stack and rag required)", ["uv", "run", "pytest", "-q"]),
    ("red-team suite: 100% of cases pass", ["uv", "run", "python", "-m", "evals.run", "redteam"]),
    (
        "SPEC section 14: every deliverable done",
        ["uv", "run", "python", "-m", "scripts.deliverables"],
    ),
]
CHECKS_BY_PHASE["4"] = [
    ("lint", ["uv", "run", "ruff", "check", "."]),
    (
        "ADR format (incl. 0010 voice framework, 0011 s2s vs cascaded)",
        ["uv", "run", "pytest", "-q", "tests/unit/test_adr_format.py"],
    ),
    (
        "TTFA and turn time p50/p95 reported; bottleneck explained",
        ["uv", "run", "python", "-m", "scripts.voice_reports", "latency"],
    ),
    (
        "medical speech recognition benchmark (WER, medical-term error rate)",
        ["uv", "run", "python", "-m", "scripts.voice_reports", "asr"],
    ),
    (
        "voice agent answers through the ClinScribe API (smoke)",
        ["uv", "run", "python", "-m", "scripts.voice_smoke"],
    ),
]
# a missing service fails the gate instead of skipping its tests
REQUIRE = {
    "1": ["CLINSCRIBE_REQUIRE_STACK"],
    "2": ["CLINSCRIBE_REQUIRE_STACK", "CLINSCRIBE_REQUIRE_RAG"],
    "3": ["CLINSCRIBE_REQUIRE_STACK", "CLINSCRIBE_REQUIRE_RAG"],
    "4": ["CLINSCRIBE_REQUIRE_STACK", "CLINSCRIBE_REQUIRE_RAG"],
    "5": ["CLINSCRIBE_REQUIRE_STACK", "CLINSCRIBE_REQUIRE_RAG"],
    "6": ["CLINSCRIBE_REQUIRE_STACK", "CLINSCRIBE_REQUIRE_RAG"],
}


def main(argv: list[str]) -> int:
    phase = argv[0] if argv else ""
    if phase not in CHECKS_BY_PHASE:
        print(f"usage: gate {{{'|'.join(CHECKS_BY_PHASE)}}}")
        return 2
    env = {**os.environ, **dict.fromkeys(REQUIRE[phase], "1")}
    results = []
    for name, cmd in CHECKS_BY_PHASE[phase]:
        started = time.monotonic()
        proc = subprocess.run(cmd, env=env, check=False)
        results.append((name, proc.returncode == 0, time.monotonic() - started))

    print(f"\nPhase {phase} exit gate")
    for name, ok, seconds in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} ({seconds:.0f} s)")
    passed = all(ok for _, ok, _ in results)
    print(f"Phase {phase}: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
