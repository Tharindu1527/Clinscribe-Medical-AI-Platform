"""Run evaluation suites: `uv run python -m evals.run privacy` (or `all`).

Reports are written to evals/reports/.
"""

import sys
from collections.abc import Callable

from evals.lab import hl7_eval, lab_eval
from evals.llmops import failover_latency
from evals.privacy import deid_eval, leak_test
from evals.rag import retrieval_eval
from evals.redteam import run as redteam

# `all` runs every suite; `leak` and `latency` need the stack and make real LLM calls
SUITES: dict[str, list[Callable[[], int]]] = {
    "privacy": [deid_eval.main],
    "leak": [leak_test.main],
    "latency": [failover_latency.main],
    # needs `just up rag` and `just index`; local encoder only, no LLM calls
    "rag": [lambda: retrieval_eval.main([])],
    # Phase 3 gate: adversarial model, real graph/guardrails/fhir-mcp code, no LLM calls
    "redteam": [lambda: redteam.main([])],
    # Lab mode, PDF and HL7 v2 ORU^R01; needs `just up` + `just fhir-load`; no LLM calls
    "lab": [lambda: lab_eval.main([]), lambda: hl7_eval.main([])],
}


def main(argv: list[str]) -> int:
    name = argv[0] if argv else "all"
    if name != "all" and name not in SUITES:
        print(f"unknown suite {name!r}; choose from: all, {', '.join(SUITES)}")
        return 2
    selected = SUITES.values() if name == "all" else [SUITES[name]]
    failures = sum(1 for suite in selected for run in suite if run() != 0)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
