"""Prompts as code (SPEC section 7, ADR-0026): every prompt file has the contract its code reads,
renders with exactly the inputs the code supplies, and its version names one text (the lock)."""

import json
import string
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from agents.prompts import Prompt as AgentPrompt
from llmops.prompt_lock import LOCK, PROMPTS, ROOT, fingerprint, load, problems, prompt_files, scan
from llmops.prompts import load_prompt
from retrieval.contextual import load_prompt as load_contextual
from retrieval.generate import load_spec

FILES = prompt_files()
MODELS = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))["tasks"]
GATEWAY = yaml.safe_load((ROOT / "llmops" / "gateway" / "config.yaml").read_text(encoding="utf-8"))
ALIASES = {m["model_name"] for m in GATEWAY["model_list"]}

# The loader each prompt's code uses, and the fields its code fills into the `user` template
# (and, for the cited answer, the system). A template asking for anything else fails here, not
# with a KeyError in a request.
LOADERS: dict[str, Callable[[Path], Any]] = {
    "answer_cited": load_spec,
    "contextual_prefix": load_contextual,
    "dev_complete": lambda path: load_prompt(path.stem, path.parent),
    "grade_evidence": lambda path: AgentPrompt.model_validate(_data(path)),
    "note_writer": lambda path: AgentPrompt.model_validate(_data(path)),
    "rewrite_query": lambda path: AgentPrompt.model_validate(_data(path)),
    "judge_citations": lambda path: _data(path)["user"],  # evals read the dict as is
    "judge_note": lambda path: int(_data(path)["max_facts"]),
    "judge_note_support": lambda path: _data(path)["user"],
}
INPUTS: dict[str, set[str]] = {
    "answer_cited": {"question", "sources"},  # retrieval/generate.py
    "contextual_prefix": {"title", "source", "section", "excerpt", "chunk"},  # retrieval/contextual
    "grade_evidence": {"question", "sources"},  # agents/graph.py
    "note_writer": {"transcript"},
    "rewrite_query": {"question"},
    "judge_citations": {"question", "reference", "sources", "sentences"},  # evals/rag/answer_eval
    "judge_note": {"reference", "statements", "max_facts"},  # evals/agents/note_quality.py
    "judge_note_support": {"turns", "statements"},
}
FORMATTED_SYSTEM = {"answer_cited": {"max_sentences"}}  # every other system is sent as written


def _data(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded


def _fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name is not None}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(PROMPTS).as_posix())
def test_every_prompt_has_the_contract_its_code_reads(path: Path) -> None:
    data = _data(path)
    assert {"id", "version", "task", "temperature", "max_tokens", "system"} <= set(data)
    assert isinstance(data["version"], str), 'quote the version, e.g. version: "2"'
    assert MODELS.get(data["task"]) in ALIASES, f"task {data['task']} has no gateway alias"
    assert 0.0 <= data["temperature"] <= 2.0
    assert data["max_tokens"] > 0
    assert data.get("reasoning_effort", "low") in ("low", "medium", "high")
    if path.parent == PROMPTS:
        assert data["id"] == path.stem
    else:  # a trial keeps the id of the prompt it would replace, under a version of its own
        production = _data(PROMPTS / f"{data['id']}.yaml")
        assert data["version"] != production["version"]
    LOADERS[data["id"]](path)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(PROMPTS).as_posix())
def test_every_template_asks_for_exactly_what_its_code_supplies(path: Path) -> None:
    data = _data(path)
    assert _fields(data.get("user", "")) == INPUTS.get(data["id"], set())
    if data["id"] in FORMATTED_SYSTEM:
        assert _fields(data["system"]) == FORMATTED_SYSTEM[data["id"]]
        data["system"].format(**{name: 1 for name in FORMATTED_SYSTEM[data["id"]]})
    if "user" in data:
        data["user"].format(**{name: "x" for name in INPUTS[data["id"]]})


def test_every_prompt_version_is_locked_and_unchanged() -> None:
    found, duplicates = scan(FILES)
    assert duplicates == []
    assert problems(load(), found) == [], "see llmops/prompt_lock.py"
    assert LOCK.read_text(encoding="utf-8").endswith("}\n")


def test_a_changed_prompt_needs_a_new_version(tmp_path: Path) -> None:
    prompt = tmp_path / "prompts" / "demo.yaml"
    prompt.parent.mkdir()
    prompt.write_text("id: demo\nversion: '1'\nsystem: Answer.\n", encoding="utf-8")
    found, _ = scan([prompt], root=tmp_path)
    lock = dict(found)
    assert problems(lock, found) == []

    prompt.write_text("id: demo\nversion: '1'\nsystem: Answer briefly.\n", encoding="utf-8")
    changed, _ = scan([prompt], root=tmp_path)
    assert "changed after it was locked" in problems(lock, changed)[0]

    prompt.write_text("id: demo\nversion: '2'\nsystem: Answer briefly.\n", encoding="utf-8")
    bumped, _ = scan([prompt], root=tmp_path)
    assert "is not locked" in problems(lock, bumped)[0]


def test_comments_and_line_endings_do_not_change_the_fingerprint() -> None:
    plain = yaml.safe_load("id: demo\nversion: '1'\nsystem: |\n  Answer.\n  Cite.\n")
    commented = yaml.safe_load(
        "# a note\r\nid: demo  # x\r\nversion: '1'\r\nsystem: |\r\n  Answer.\r\n  Cite.\r\n"
    )
    assert fingerprint(plain) == fingerprint(commented)
    assert fingerprint(plain) != fingerprint({**plain, "temperature": 0.2})


def test_two_files_cannot_claim_one_version(tmp_path: Path) -> None:
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(f"id: demo\nversion: '1'\nsystem: {name}\n", encoding="utf-8")
    _, duplicates = scan(sorted(tmp_path.glob("*.yaml")), root=tmp_path)
    assert duplicates == ["demo@v1 is declared by both a.yaml and b.yaml"]


def test_the_lock_is_sorted_json() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    assert list(lock) == sorted(lock)
