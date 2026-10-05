"""Run a phase's exit gate and print one PASS/FAIL table (SPEC section 12).

Usage: uv run python -m scripts.gate 1
Phase 1 gate: (a) gateway answers when the primary fails; (b) the leak test finds 0 PHI in traces
and logs; (c) Synthea patients are queryable from FHIR. Supporting checks: the full test suite with
the stack required, and the audit hash chain.
Needs `just up` and `just fhir-load`; makes real LLM calls.
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
            "(a) gateway answers when the primary fails",
            ["uv", "run", "pytest", "-q", "-m", "live", "tests/live/test_gateway_failover.py"],
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
}


def main(argv: list[str]) -> int:
    phase = argv[0] if argv else ""
    if phase not in CHECKS_BY_PHASE:
        print(f"usage: gate {{{'|'.join(CHECKS_BY_PHASE)}}}")
        return 2
    env = {**os.environ, "CLINSCRIBE_REQUIRE_STACK": "1"}  # a missing stack fails, never skips
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
