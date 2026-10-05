"""Run evaluation suites: `uv run python -m evals.run privacy` (or `all`).

Reports are written to evals/reports/.
"""

import sys
from collections.abc import Callable

from evals.privacy import deid_eval, leak_test

# `all` runs every suite; `leak` needs the stack and makes ~20 real LLM calls
SUITES: dict[str, list[Callable[[], int]]] = {
    "privacy": [deid_eval.main],
    "leak": [leak_test.main],
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
