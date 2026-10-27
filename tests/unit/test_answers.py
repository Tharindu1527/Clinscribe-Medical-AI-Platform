"""Cited answers: reply validation, retry, safe reply, judge parsing, metrics, rate limits."""

from collections.abc import Sequence
from typing import Any

import httpx
import pytest

from evals.golden.golden import GoldenItem, load_items
from evals.rag.answer_eval import (
    BudgetExhaustedError,
    PatientClient,
    metrics,
    parse_judgment,
    stratified_subset,
    wait_seconds,
)
from llmops.gateway.client import ChatMessage, Completion
from privacy.deid.types import issue
from retrieval.generate import (
    AnswerGenerator,
    CitedAnswer,
    CitedSentence,
    load_spec,
    parse_reply,
    source_block,
)

CHUNKS = [
    {
        "id": "fda:x#s0#c0",
        "title": "Warfarin label",
        "section": "Dosage",
        "text": "Start 2 to 5 mg.",
    },
    {
        "id": "pmc:P1#s1#c0",
        "title": "Review",
        "section": "Results",
        "text": "INR rose with azoles.",
    },
]
LABELS = source_block(CHUNKS)[1]


def test_source_block_labels_chunks_in_order() -> None:
    text, labels = source_block(CHUNKS)
    assert labels == {"S1": "fda:x#s0#c0", "S2": "pmc:P1#s1#c0"}
    assert text.startswith("[S1] Warfarin label — Dosage\nStart 2 to 5 mg.")


def test_parse_reply_maps_labels_and_rejects_bad_citations() -> None:
    abstained, sentences = parse_reply(
        'Sure: {"abstain": false, "sentences": [{"text": "Start low.", "sources": ["S1", "S1"]}]}',
        LABELS,
        4,
    )
    assert not abstained
    assert sentences[0].chunk_ids == ["fda:x#s0#c0"]  # duplicates removed
    assert parse_reply('{"abstain": true, "sentences": []}', LABELS, 4) == (True, [])
    bad = {
        '{"abstain": false, "sentences": [{"text": "x", "sources": []}]}': "cites no source",
        '{"abstain": false, "sentences": [{"text": "x", "sources": ["S9"]}]}': "unknown sources",
        '{"abstain": true, "sentences": [{"text": "x", "sources": ["S1"]}]}': "abstain",
        '{"sentences": []}': "boolean",
        "no json at all": "no JSON",
    }
    for reply, message in bad.items():
        with pytest.raises(ValueError, match=message):
            parse_reply(reply, LABELS, 4)


class _Scripted:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls: list[Sequence[ChatMessage]] = []

    def complete(self, model: str, messages: Sequence[ChatMessage], **kwargs: Any) -> Completion:
        self.calls.append(messages)
        return Completion(
            text=self.replies.pop(0), model="m", input_tokens=1, output_tokens=1, latency_ms=1.0
        )


def test_invalid_reply_is_retried_once_with_the_error_then_safe_reply() -> None:
    good = '{"abstain": false, "sentences": [{"text": "Start low.", "sources": ["S1"]}]}'
    client = _Scripted(["not json", good])
    answer = AnswerGenerator(client, "m").answer(issue("Dose?", "synthetic-test-fixture"), CHUNKS)
    assert (answer.abstained, answer.attempts, answer.sentences[0].text) == (False, 2, "Start low.")
    assert "Your reply was invalid" in client.calls[1][-1].content.text
    failing = _Scripted(["nope", "still nope"])
    answer = AnswerGenerator(failing, "m").answer(issue("Dose?", "synthetic-test-fixture"), CHUNKS)
    assert answer.abstained
    assert answer.error is not None
    with pytest.raises(TypeError):
        AnswerGenerator(failing, "m").answer("Dose?", CHUNKS)  # type: ignore[arg-type]


def _item(answerable: bool = True) -> GoldenItem:
    return GoldenItem(
        id="g0001",
        question="What dose of warfarin is started?",
        answerable=answerable,
        answer="2 to 5 mg" if answerable else None,
        gold_chunk_ids=["fda:x#s0#c0"] if answerable else [],
        absent_terms=[] if answerable else ["zzz"],
        area="anticoagulation",
        qtype="dose",
        source="openfda" if answerable else None,
        drafted_by="test",
    )


ANSWER = CitedAnswer(
    abstained=False,
    sentences=[
        CitedSentence(text="Start 2 to 5 mg.", chunk_ids=["fda:x#s0#c0"]),
        CitedSentence(text="INR may rise.", chunk_ids=["fda:x#s0#c0", "pmc:P1#s1#c0"]),
    ],
    prompt="answer_cited@v1",
    model="m",
    attempts=1,
)


def test_judgment_parsing_and_metrics() -> None:
    reply = (
        '{"sentences": [{"n": 1, "cited": {"S1": "supports"}, "supported_by": ["S1"]},'
        ' {"n": 2, "cited": {"S1": "no", "S2": "supports"}, "supported_by": ["S2", "S7"]}],'
        ' "matches_reference": "partial"}'
    )
    judgment = parse_judgment(reply, ANSWER, LABELS)
    assert judgment["sentences"][1]["supported_by"] == ["S2"]  # unknown label dropped
    found = metrics(_item(), ANSWER, judgment)
    assert found["citation_precision"] == pytest.approx(2 / 3)  # 2 of 3 cited links support
    assert found["faithfulness"] == 1.0
    assert found["correctness"] == 0.5
    with pytest.raises(ValueError, match="rated 1 of 2"):
        parse_judgment('{"sentences": [{"n": 1}], "matches_reference": "yes"}', ANSWER, LABELS)


def test_abstention_metrics() -> None:
    abstained = ANSWER.model_copy(update={"abstained": True, "sentences": []})
    assert metrics(_item(False), abstained, None) == {
        "abstained": True,
        "answerable": False,
        "correct_abstain": True,
    }
    assert metrics(_item(True), abstained, None)["correctness"] == 0.0


def test_rate_limit_waits_are_parsed_and_long_waits_stop_the_run() -> None:
    def response(text: str, headers: dict[str, str] | None = None) -> httpx.Response:
        return httpx.Response(
            429, text=text, headers=headers or {}, request=httpx.Request("POST", "http://gateway")
        )

    assert wait_seconds(response("Please try again in 1m2.5s.")) == pytest.approx(62.5)
    assert wait_seconds(response("x", {"retry-after": "7"})) == 7.0
    assert wait_seconds(response("Please try again in 2h3m")) == 7380.0

    class _Limited:
        def complete(self, *args: Any, **kwargs: Any) -> Completion:
            raise httpx.HTTPStatusError(
                "429",
                request=httpx.Request("POST", "http://g"),
                response=response("Please try again in 3h"),
            )

    with pytest.raises(BudgetExhaustedError):
        PatientClient(_Limited()).complete("m", [])  # type: ignore[arg-type]


def test_patient_client_can_keep_a_trial_on_the_named_model() -> None:
    seen: list[dict[str, Any]] = []

    class _Recording:
        def complete(self, *args: Any, **kwargs: Any) -> Completion:
            seen.append(kwargs)
            return Completion("ok", "m", 1, 1, 1.0)

    PatientClient(_Recording()).complete("m", [], max_tokens=8)  # type: ignore[arg-type]
    PatientClient(_Recording(), fallbacks=False).complete("m", [])  # type: ignore[arg-type]
    assert seen == [{"max_tokens": 8}, {"fallbacks": False}]


def test_subset_is_stratified_and_seeded() -> None:
    subset = stratified_subset(load_items())
    assert len(subset) == 60
    assert sum(not i.answerable for i in subset) == 10
    assert len({i.area for i in subset}) == 5
    assert stratified_subset(load_items()) == subset


def test_the_prompt_sets_the_reasoning_effort_or_sends_none() -> None:
    # ADR-0025: an effort in the prompt file reaches the gateway; without one nothing is sent,
    # so the production prompt's cached requests keep their keys
    good = '{"abstain": false, "sentences": [{"text": "Start low.", "sources": ["S1"]}]}'
    sent: list[Any] = []

    class Recording(_Scripted):
        def complete(
            self, model: str, messages: Sequence[ChatMessage], **kwargs: Any
        ) -> Completion:
            sent.append(kwargs.get("reasoning_effort"))
            return super().complete(model, messages, **kwargs)

    question = issue("Dose?", "synthetic-test-fixture")
    AnswerGenerator(Recording([good]), "m").answer(question, CHUNKS)
    low = load_spec().model_copy(update={"reasoning_effort": "low"})
    AnswerGenerator(Recording([good]), "m", low).answer(question, CHUNKS)
    assert sent == [None, "low"]
