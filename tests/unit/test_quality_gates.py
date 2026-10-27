"""CI quality gates (ADR-0026; SPEC section 11 "regression gates in CI"): the committed answer
evaluation covers the repo's prompts and model and meets its floors; the red-team suite passes
and its control fails; the de-ID recall and over-redaction gates hold. No LLM calls, no stack."""

import copy
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from config.settings import Settings
from evals.privacy.deid_eval import deidentifier_for, evaluate
from evals.quality_gates import GATES, GATEWAY, MODELS, answer_problems, check, prompt_ref
from evals.rag.answer_eval import load_rows
from evals.redteam.run import CONTROLLED, run_suite

GATE = yaml.safe_load(GATES.read_text(encoding="utf-8"))["answer"]
TASKS = yaml.safe_load(MODELS.read_text(encoding="utf-8"))["tasks"]
ROUTER = yaml.safe_load(GATEWAY.read_text(encoding="utf-8"))


def _inputs() -> dict[str, Any]:
    return {
        "gate": GATE,
        "rows": load_rows(GATE["system"]),
        "refs": {p: prompt_ref(p) for p in GATE["prompts"].values()},
        "tasks": dict(TASKS),
        "gateway": copy.deepcopy(ROUTER),
    }


def test_the_committed_answer_evaluation_covers_the_repo_and_meets_its_floors() -> None:
    measured, problems = check()
    assert problems == []
    assert measured["questions"] == GATE["questions"]


def test_a_new_prompt_version_needs_a_new_evaluation() -> None:
    inputs = _inputs()
    inputs["refs"]["answer_cited"] = "answer_cited@v2"
    assert "run the answer evaluation for the new version" in answer_problems(**inputs)[0]


def test_a_model_switch_needs_a_new_evaluation() -> None:
    inputs = _inputs()
    inputs["tasks"]["answer_cited"] = "clinscribe-default"
    assert answer_problems(**inputs) == [
        "task answer_cited now uses clinscribe-default; the evaluation used "
        "clinscribe-fallback-groq"
    ]
    inputs = _inputs()
    for model in inputs["gateway"]["model_list"]:
        if model["model_name"] == GATE["alias"]:
            model["litellm_params"]["model"] = "groq/openai/gpt-oss-120b"
    assert "the evaluation used groq/openai/gpt-oss-20b" in answer_problems(**inputs)[0]


def test_a_quality_drop_fails_the_gate() -> None:
    inputs = _inputs()
    rows = copy.deepcopy(inputs["rows"])
    for row in rows.values():  # every answered question loses half its faithfulness
        if "faithfulness" in row["metrics"]:
            row["metrics"]["faithfulness"] /= 2
    inputs["rows"] = rows
    assert [p for p in answer_problems(**inputs) if p.startswith("faithfulness")] != []
    inputs["rows"] = dict(list(rows.items())[:50])
    assert "50 questions in the rows, the gate needs 60" in answer_problems(**inputs)


def test_every_red_team_case_passes() -> None:
    failed = [(case["id"], detail) for case, ok, detail in run_suite() if not ok]
    assert failed == []


def test_the_red_team_control_fails_every_case_its_rules_cover() -> None:
    """With the dose, diagnosis and injection rules and the subject checks switched off, the
    cases that rely on them fail: the suite can fail at all."""
    results = run_suite(control=True)
    covered = [(case["id"], ok) for case, ok, _ in results if case["category"] in CONTROLLED]
    assert len(covered) >= 30
    assert [case_id for case_id, ok in covered if ok] == []


@pytest.fixture(scope="module")
def deid_summary() -> dict[str, Any]:
    """The service's default recogniser (spaCy, as in CI and a fresh clone; the tagger of
    ADR-0014 is opt-in and evaluated with `just eval privacy`)."""
    model = Settings.model_fields["deid_spacy_model"].default
    summary, _, _ = evaluate(deidentifier_for("spacy", model))
    return summary


def test_deid_recall_and_over_redaction_gates_hold(deid_summary: dict[str, Any]) -> None:
    assert deid_summary["failed"] == []
    assert deid_summary["snippets"] == 200


class _ChangesNothing:
    def deidentify(self, text: str, encounter_id: str) -> SimpleNamespace:
        return SimpleNamespace(text=SimpleNamespace(text=text), replacements=[])


def test_a_deidentifier_that_misses_phi_fails_the_gates() -> None:
    summary, _, _ = evaluate(_ChangesNothing())
    assert "PERSON recall 0.000 < 0.99" in summary["failed"]
    assert len(summary["failed"]) >= 15
