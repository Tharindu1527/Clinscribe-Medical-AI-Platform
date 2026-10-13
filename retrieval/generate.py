"""Cited answers from retrieved chunks (SPEC section 6 fast path, step 3; Phase 2 task 10).

The model sees the question and the top chunks labelled [S1]..[Sn] and must return JSON in which
every sentence cites at least one label. The reply is re-validated in code (labels must exist,
every sentence needs a citation, abstention must be explicit); an invalid reply is retried once with
the error attached, then replaced by the safe reply (SPEC section 5 guardrails).
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, Field

from llmops.gateway.client import ChatMessage, Completion
from privacy.deid.types import DeidentifiedText, issue

ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILE = ROOT / "prompts" / "answer_cited.yaml"


class AnswerSpec(BaseModel):
    id: str
    version: str
    task: str
    temperature: float
    max_tokens: int
    max_sentences: int
    safe_reply: str
    system: str
    user: str


class CitedSentence(BaseModel):
    text: str = Field(min_length=1)
    chunk_ids: list[str] = Field(min_length=1)


class CitedAnswer(BaseModel):
    abstained: bool
    sentences: list[CitedSentence]
    prompt: str  # "<id>@v<version>", written into traces and audit records
    model: str
    attempts: int
    error: str | None = None  # set when the safe reply replaced two invalid replies

    def text(self, safe_reply: str) -> str:
        return safe_reply if self.abstained else " ".join(s.text for s in self.sentences)


class Chat(Protocol):
    def complete(
        self,
        model: str,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
        response_format: dict[str, object] | None = None,
    ) -> Completion: ...


def load_spec(path: Path = PROMPT_FILE) -> AnswerSpec:
    return AnswerSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def source_block(chunks: Sequence[Mapping[str, str]]) -> tuple[str, dict[str, str]]:
    """'[S1] title — section\\ntext' blocks, and label -> chunk id."""
    labels = {f"S{i}": c["id"] for i, c in enumerate(chunks, start=1)}
    blocks = [
        f"[S{i}] {c['title']} — {c['section']}\n{c['text']}" for i, c in enumerate(chunks, start=1)
    ]
    return "\n\n".join(blocks), labels


def parse_reply(
    text: str, labels: Mapping[str, str], max_sentences: int
) -> tuple[bool, list[CitedSentence]]:
    """Validate the model's JSON; raises ValueError with a message the model can act on."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("the reply contains no JSON object")
    try:
        data: Any = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"the reply is not valid JSON ({exc.msg})") from None
    if not isinstance(data, dict) or not isinstance(data.get("abstain"), bool):
        raise ValueError('the JSON needs a boolean "abstain" field')
    sentences = data.get("sentences")
    if not isinstance(sentences, list):
        raise ValueError('the JSON needs a "sentences" list')
    if data["abstain"]:
        if sentences:
            raise ValueError('"abstain" is true but sentences were given')
        return True, []
    if not sentences:
        raise ValueError('"abstain" is false but there are no sentences')
    if len(sentences) > max_sentences:
        raise ValueError(f"use at most {max_sentences} sentences")
    out = []
    for n, sentence in enumerate(sentences, start=1):
        if not isinstance(sentence, dict) or not str(sentence.get("text", "")).strip():
            raise ValueError(f"sentence {n} has no text")
        cited = sentence.get("sources")
        if not isinstance(cited, list) or not cited:
            raise ValueError(f"sentence {n} cites no source")
        unknown = [s for s in cited if s not in labels]
        if unknown:
            raise ValueError(
                f"sentence {n} cites unknown sources {unknown}; use only {list(labels)}"
            )
        ids = list(dict.fromkeys(labels[s] for s in cited))
        out.append(CitedSentence(text=str(sentence["text"]).strip(), chunk_ids=ids))
    return False, out


class AnswerGenerator:
    def __init__(self, client: Chat, model: str, spec: AnswerSpec | None = None) -> None:
        self._client = client
        self._model = model
        self.spec = spec or load_spec()

    def answer(
        self,
        question: DeidentifiedText,
        chunks: Sequence[Mapping[str, str]],
        feedback: str | None = None,
    ) -> CitedAnswer:
        """Question must be de-identified; chunks are public corpus text (ADR-0001). `feedback`
        (guardrail violations of a previous answer) is appended only when given, so earlier cached
        requests keep their keys."""
        if not isinstance(question, DeidentifiedText):
            raise TypeError("the question must be DeidentifiedText")
        spec = self.spec
        sources, labels = source_block(chunks)
        system = spec.system.format(max_sentences=spec.max_sentences)
        messages = [
            ChatMessage("system", issue(system, "prompt")),
            ChatMessage(
                "user",
                issue(
                    spec.user.format(question=question.text, sources=sources)
                    + (
                        f"\n\nYour previous answer was rejected: {feedback}. Fix it."
                        if feedback
                        else ""
                    ),
                    f"{question.source}+public-corpus",
                ),
            ),
        ]
        error = None
        for attempt in (1, 2):
            reply = self._client.complete(
                self._model,
                messages,
                temperature=spec.temperature,
                max_tokens=spec.max_tokens,
                response_format={"type": "json_object"},
            )
            try:
                abstained, sentences = parse_reply(reply.text, labels, spec.max_sentences)
                return CitedAnswer(
                    abstained=abstained,
                    sentences=sentences,
                    prompt=f"{spec.id}@v{spec.version}",
                    model=reply.model,
                    attempts=attempt,
                )
            except ValueError as exc:
                error = str(exc)
                messages = [
                    *messages,
                    ChatMessage("assistant", issue(reply.text, "model-output")),
                    ChatMessage(
                        "user",
                        issue(
                            f"Your reply was invalid: {error}. Reply again with valid JSON only.",
                            "prompt",
                        ),
                    ),
                ]
        return CitedAnswer(
            abstained=True,
            sentences=[],
            prompt=f"{spec.id}@v{spec.version}",
            model=self._model,
            attempts=2,
            error=error,
        )
