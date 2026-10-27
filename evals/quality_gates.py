"""CI quality gates on committed evidence (ADR-0026; config/quality_gates.yaml).

The answer evaluation needs provider keys, so its rows are made locally and committed; this checks,
with no calls, that they were made with the prompts and the model the repo now uses and that they
meet the floors. CI runs it through tests/unit/test_quality_gates.py, together with the red-team
suite, the de-ID gates and the prompt lock.

  uv run python -m evals.quality_gates   measured values against their floors; exit 1 on a problem
"""

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from evals.rag.answer_eval import load_rows, summary

ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "config" / "quality_gates.yaml"
MODELS = ROOT / "config" / "models.yaml"
GATEWAY = ROOT / "llmops" / "gateway" / "config.yaml"
PROMPTS = ROOT / "prompts"


def prompt_ref(prompt_id: str, directory: Path = PROMPTS) -> str:
    data = yaml.safe_load((directory / f"{prompt_id}.yaml").read_text(encoding="utf-8"))
    return f"{data['id']}@v{data['version']}"


def deployment(alias: str, gateway: Mapping[str, Any]) -> list[str]:
    """The provider models behind a gateway alias (more than one for a load-balanced pool)."""
    return [m["litellm_params"]["model"] for m in gateway["model_list"] if m["model_name"] == alias]


def answer_problems(
    gate: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
    refs: Mapping[str, str],
    tasks: Mapping[str, str],
    gateway: Mapping[str, Any],
) -> list[str]:
    """Why the committed answer evaluation does not cover the repo as it is, or falls short."""
    out = []
    expected = {field: refs[prompt] for field, prompt in gate["prompts"].items()}
    made_with = {tuple(sorted(r["versions"].items())) for r in rows.values()}
    if made_with != {tuple(sorted(expected.items()))}:
        out.append(
            f"answer rows were made with {[dict(v) for v in sorted(made_with)]}, the repo uses "
            f"{expected}: run the answer evaluation for the new version and commit its rows"
        )
    alias = tasks.get(gate["task"])
    if alias != gate["alias"]:
        out.append(f"task {gate['task']} now uses {alias}; the evaluation used {gate['alias']}")
    served = deployment(gate["alias"], gateway)
    if served != [gate["deployment"]]:
        out.append(f"{gate['alias']} is now {served}; the evaluation used {gate['deployment']}")
    measured = summary(rows)
    if measured["questions"] != gate["questions"]:
        out.append(
            f"{measured['questions']} questions in the rows, the gate needs {gate['questions']}"
        )
    models = set(measured["generator_models"])
    if models - {gate["alias"]}:
        out.append(f"answers served by {sorted(models)}, not only {gate['alias']}")
    for metric, floor in gate["min"].items():
        value = measured[metric]
        if value is None or value < floor:
            out.append(f"{metric} {value} is below its floor {floor}")
    for metric, ceiling in gate["max"].items():
        if measured[metric] > ceiling:
            out.append(f"{metric} {measured[metric]} is above its ceiling {ceiling}")
    return out


def check(gates_file: Path = GATES) -> tuple[dict[str, Any], list[str]]:
    gates = yaml.safe_load(gates_file.read_text(encoding="utf-8"))
    gate = gates["answer"]
    rows = load_rows(gate["system"])
    refs = {p: prompt_ref(p) for p in gate["prompts"].values()}
    tasks = yaml.safe_load(MODELS.read_text(encoding="utf-8"))["tasks"]
    gateway = yaml.safe_load(GATEWAY.read_text(encoding="utf-8"))
    return summary(rows), answer_problems(gate, rows, refs, tasks, gateway)


def main() -> int:
    measured, problems = check()
    gate = yaml.safe_load(GATES.read_text(encoding="utf-8"))["answer"]
    for metric, floor in gate["min"].items():
        print(f"{metric:22} {measured[metric]!s:>6}  floor {floor}")
    for metric, ceiling in gate["max"].items():
        print(f"{metric:22} {measured[metric]!s:>6}  ceiling {ceiling}")
    for problem in problems:
        print(f"FAIL {problem}")
    print("answer gate:", "FAIL" if problems else "PASS")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
