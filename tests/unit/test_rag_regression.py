"""CI retrieval regression (Phase 2 task 12): first-stage metrics on the committed mini fixture.

A drop below the committed thresholds means a change to tokenisation, BM25, RRF, the metrics or
the fixture itself; rebuild the fixture (`uv run python -m evals.rag.fixture`) only for an
intended change, and say why in the commit.
"""

import json

import pytest

from evals.rag.fixture import FIXTURE, evaluate


@pytest.fixture(scope="module")
def measured() -> dict[str, dict[str, float]]:
    return evaluate()


def test_fixture_holds_only_committable_sources() -> None:
    lines = (FIXTURE / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert {r["source"] for r in rows} <= {"openfda", "pmc"}
    assert all(r["url"] and r["license"] for r in rows)
    questions = (FIXTURE / "questions.jsonl").read_text(encoding="utf-8").splitlines()
    ids = {r["id"] for r in rows}
    assert all(set(json.loads(q)["gold_chunk_ids"]) <= ids for q in questions)


@pytest.mark.parametrize("system", ["dense", "bm25", "hybrid"])
def test_retrieval_metrics_stay_above_thresholds(
    measured: dict[str, dict[str, float]], system: str
) -> None:
    thresholds = json.loads((FIXTURE / "thresholds.json").read_text(encoding="utf-8"))
    for metric, floor in thresholds["thresholds"][system].items():
        assert measured[system][metric] >= floor, f"{system} {metric} below {floor}"
