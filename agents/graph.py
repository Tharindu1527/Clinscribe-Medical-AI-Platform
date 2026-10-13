"""The ClinScribe agent graph (SPEC section 5; Phase 3 tasks 4-6).

    intake -> router -> ask_fast | ask_agentic -> answer -> guardrail_answer -> END
                     \\-> note_writer -> guardrail_note -> hitl_review -> commit -> END

- intake: text must already be de-identified; a second structured-PHI check refuses it otherwise.
- router (ask mode): the agentic loop for drug-interaction, comparison and multi-part questions,
  the fast path for simple lookups (ablation step 7 measures the choice).
- ask_fast: search_guidelines (k 5). ask_agentic (CRAG style): search deeper, grade the passages
  with a model, rewrite the query once if fewer than two are relevant, add DDInter facts for drug
  questions. Passages with prompt-injection text are dropped in both paths.
- answer + guardrail_answer: cited answer; on a violation, one retry with the violations attached,
  then the safe reply.
- note_writer + guardrail_note: SOAP statements tied to transcript turns; one retry with the
  problems attached, then statements that still fail are removed and listed for the doctor.
- hitl_review: LangGraph interrupt(); the doctor approves, edits or rejects. Resuming carries the
  decision, the approval token (signed by the API for the exact FHIR resource) and two identifiers.
- commit: write_fhir through fhir-mcp, which re-verifies everything (agents/approval.py).
State holds only JSON-serialisable values, so any checkpointer can store it and runs can replay.
"""

import json
import re
from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from agents.fhir_docs import note_to_resource
from agents.guardrails import Guardrails
from agents.prompts import Prompt, load
from agents.schemas import (
    AnswerSentence,
    AskAnswer,
    CheckInteractionsInput,
    Evidence,
    NoteStatement,
    ReviewDecision,
    SearchGuidelinesInput,
    SoapNote,
    WriteFhirInput,
)
from agents.tools import ToolError, Tools
from llmops.gateway.client import ChatMessage, Completion, alias_for
from privacy.deid.types import issue
from retrieval.generate import AnswerGenerator, source_block

COMPARISON = re.compile(
    r"\b(compare|comparison|versus|vs\.?|difference between|better than|which is (better|safer)|"
    r"interact\w*|together with|combin\w*|while (taking|on)|contraindicat\w*)\b",
    re.IGNORECASE,
)
STOPWORDS = frozenset(
    [
        "about",
        "above",
        "after",
        "again",
        "against",
        "also",
        "among",
        "another",
        "because",
        "before",
        "being",
        "between",
        "both",
        "could",
        "daily",
        "dose",
        "doses",
        "doing",
        "during",
        "each",
        "first",
        "given",
        "have",
        "into",
        "many",
        "might",
        "more",
        "most",
        "much",
        "other",
        "patient",
        "patients",
        "people",
        "should",
        "since",
        "some",
        "such",
        "than",
        "that",
        "their",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "under",
        "until",
        "very",
        "what",
        "when",
        "where",
        "which",
        "while",
        "with",
        "within",
        "would",
        "years",
    ]
)


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


class State(TypedDict, total=False):
    mode: Literal["ask", "scribe"]
    encounter_id: str
    actor: str
    patient_id: str
    question: str  # de-identified
    transcript: list[str]  # de-identified turns, "DOCTOR: ..." / "PATIENT: ..."
    route: Literal["fast", "agentic"]
    query: str
    evidence: list[dict[str, Any]]
    dropped: list[str]
    answer: dict[str, Any]
    note: dict[str, Any]
    violations: list[str]
    attempts: int
    feedback: str
    review: dict[str, Any]
    result: dict[str, Any]
    events: list[str]


def route_question(question: str) -> Literal["fast", "agentic"]:
    """Agentic for interaction / comparison wording, several questions, or long questions."""
    if COMPARISON.search(question) or question.count("?") > 1 or len(question.split()) > 30:
        return "agentic"
    return "fast"


def drug_candidates(question: str) -> list[str]:
    """Words that may be drug names, for check_interactions (unknown ones are reported back)."""
    words = re.findall(r"[A-Za-z][A-Za-z-]{3,}", question)
    seen = list(dict.fromkeys(w for w in words if w.lower() not in STOPWORDS))
    return seen[:10]


def _json(text: str) -> Any:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("the reply contains no JSON object")
    return json.loads(text[start : end + 1])


class Agents:
    """Graph nodes with their dependencies; `build()` wires them into a compiled graph."""

    def __init__(
        self,
        chat: Chat,
        tools: Tools,
        guardrails: Guardrails | None = None,
        alias: Callable[[str], str] = alias_for,
    ) -> None:
        self.chat = chat
        self.tools = tools
        self.guard = guardrails or Guardrails()
        self.alias = alias
        self.answerer = AnswerGenerator(chat, alias("answer_cited"))
        self.prompts = {n: load(n) for n in ("note_writer", "grade_evidence", "rewrite_query")}

    # ---------------------------------------------------------------- helpers
    def _ask_model(self, prompt: Prompt, **fields: str) -> str:
        user = prompt.user.format(**fields)
        problems = self.guard.check_deidentified(user)
        if problems:  # second line of defence: never send structured PHI to a model
            raise ValueError(f"refused to send text with PHI to a model ({problems[0]})")
        reply = self.chat.complete(
            self.alias(prompt.task),
            [
                ChatMessage("system", issue(prompt.system, "prompt")),
                ChatMessage("user", issue(user, "graph-state-deidentified")),
            ],
            temperature=prompt.temperature,
            max_tokens=prompt.max_tokens,
            response_format={"type": "json_object"},
        )
        return reply.text

    def _search(self, query: str, k: int, state: State) -> list[Evidence]:
        found = self.tools.search(SearchGuidelinesInput(query=query, k=k))
        kept, dropped = self.guard.screen_evidence(found)
        state.setdefault("dropped", []).extend(str(v) for v in dropped)
        return kept

    # ---------------------------------------------------------------- nodes
    def intake(self, state: State) -> State:
        text = state.get("question", "") + "\n".join(state.get("transcript", []))
        problems = self.guard.check_deidentified(text)
        if problems:
            return {"result": {"status": "refused", "reason": str(problems[0])}}
        return {"attempts": 0, "violations": [], "dropped": [], "events": ["intake"]}

    def after_intake(self, state: State) -> str:
        if state.get("result"):
            return END
        return "router" if state["mode"] == "ask" else "note_writer"

    def router(self, state: State) -> State:
        route = route_question(state["question"])
        return {"route": route, "query": state["question"], "events": [*state["events"], route]}

    def ask_fast(self, state: State) -> State:
        evidence = self._search(state["query"], 5, state)
        return {"evidence": [e.model_dump() for e in evidence], "dropped": state["dropped"]}

    def ask_agentic(self, state: State) -> State:
        query, events = state["query"], list(state["events"])
        relevant: list[Evidence] = []
        for round_ in (1, 2):
            candidates = self._search(query, 8, state)
            if not candidates:
                break
            sources, labels = source_block(
                [
                    {"id": e.chunk_id, "title": e.title, "section": e.section, "text": e.text}
                    for e in candidates
                ]
            )
            try:
                graded = _json(
                    self._ask_model(
                        self.prompts["grade_evidence"], question=state["question"], sources=sources
                    )
                )
                keep = {labels[s] for s in graded.get("relevant", []) if s in labels}
            except (ValueError, KeyError):
                keep = {e.chunk_id for e in candidates}  # grading failed: do not lose evidence
            relevant = [e for e in candidates if e.chunk_id in keep]
            events.append(f"graded {len(relevant)}/{len(candidates)} relevant (round {round_})")
            if len(relevant) >= 2 or round_ == 2:
                break
            try:
                query = str(
                    _json(
                        self._ask_model(self.prompts["rewrite_query"], question=state["question"])
                    )["query"]
                )
                events.append("query rewritten")
            except (ValueError, KeyError):
                break
        drugs = drug_candidates(state["question"])
        if len(drugs) >= 2:
            report = self.tools.interactions(CheckInteractionsInput(drugs=drugs))
            for fact in report.interactions:
                relevant.append(
                    Evidence(
                        chunk_id=fact.source_id,
                        text=f"{fact.drug_a} and {fact.drug_b}: {fact.severity} interaction "
                        "(DDInter 2.0). The database records the pair and its severity, not the "
                        "mechanism or management.",
                        title="DDInter 2.0 drug-drug interaction database",
                        section="Interaction severity",
                        source="ddinter",
                        source_url="https://ddinter2.scbdd.com",
                        score=1.0,
                    )
                )
            events.append(f"drug facts {len(report.interactions)}")
        return {
            "evidence": [e.model_dump() for e in relevant[:8]],
            "query": query,
            "dropped": state["dropped"],
            "events": events,
        }

    def answer(self, state: State) -> State:
        evidence = [Evidence.model_validate(e) for e in state["evidence"]]
        chunks = [
            {"id": e.chunk_id, "title": e.title, "section": e.section, "text": e.text}
            for e in evidence
        ]
        cited = self.answerer.answer(
            issue(state["question"], "graph-state-deidentified"), chunks, state.get("feedback")
        )
        answer = AskAnswer(
            question_id=state["encounter_id"],
            abstained=cited.abstained or not chunks,
            sentences=[]
            if cited.abstained or not chunks
            else [AnswerSentence(text=s.text, citations=s.chunk_ids) for s in cited.sentences],
            path=state["route"],
            prompt_version=cited.prompt,
            model=cited.model,
        )
        return {"answer": answer.model_dump(), "attempts": state["attempts"] + 1}

    def guardrail_answer(self, state: State) -> State:
        answer = AskAnswer.model_validate(state["answer"])
        sources = {e["chunk_id"]: e["text"] for e in state["evidence"]}
        problems = [str(v) for v in self.guard.check_answer(answer, sources)]
        if not problems:
            return {"violations": [], "feedback": ""}
        if state["attempts"] < self.guard.max_attempts:
            return {"violations": problems, "feedback": "; ".join(problems)}
        safe = answer.model_copy(update={"abstained": True, "sentences": []})
        return {"answer": safe.model_dump(), "violations": problems, "feedback": ""}

    def after_guardrail_answer(self, state: State) -> str:
        return "answer" if state.get("feedback") else END

    def note_writer(self, state: State) -> State:
        turns = "\n".join(f"[{n}] {t}" for n, t in enumerate(state["transcript"]))
        prompt = self.prompts["note_writer"]
        feedback = state.get("feedback")
        extra = f"\n\nYour previous note was rejected: {feedback}. Fix it." if feedback else ""
        reply = self._ask_model(prompt, transcript=turns + extra)
        statements, problems = [], []
        try:
            for n, raw in enumerate(_json(reply).get("statements", []), start=1):
                try:
                    statements.append(
                        NoteStatement(
                            section=raw.get("section"),
                            text=str(raw.get("text", "")).strip(),
                            transcript_turns=[int(t) for t in raw.get("turns", [])],
                        )
                    )
                except (ValidationError, TypeError, ValueError) as exc:
                    problems.append(f"statement {n} invalid: {str(exc).splitlines()[0]}")
        except ValueError as exc:
            problems.append(str(exc))
        note = {
            "encounter_id": state["encounter_id"],
            "statements": [s.model_dump() for s in statements],
            "prompt_version": prompt.ref,
            "model": self.alias(prompt.task),
        }
        return {"note": note, "violations": problems, "attempts": state["attempts"] + 1}

    def guardrail_note(self, state: State) -> State:
        statements = [NoteStatement.model_validate(s) for s in state["note"]["statements"]]
        problems = list(state.get("violations", []))  # parse errors from note_writer
        checked = []
        if statements:
            note = SoapNote.model_validate(state["note"])
            checked = self.guard.check_note(note, state["transcript"], {})
            problems += [str(v) for v in checked]
        else:
            problems.append("the note has no valid statements")
        if problems and state["attempts"] < self.guard.max_attempts:
            return {"violations": problems, "feedback": "; ".join(problems)}
        # numbering comes from check_note over the validated statements, not from parse errors
        bad = {int(m.group(1)) for v in checked if (m := re.match(r"statement (\d+)", v.detail))}
        kept = [s for n, s in enumerate(statements, start=1) if n not in bad]
        trimmed = {**state["note"], "statements": [s.model_dump() for s in kept]}
        return {"note": trimmed, "violations": problems, "feedback": ""}

    def after_guardrail_note(self, state: State) -> str:
        if state.get("feedback"):
            return "note_writer"
        return "hitl_review" if state["note"]["statements"] else END

    def hitl_review(self, state: State) -> State:
        note = SoapNote.model_validate(state["note"])
        review = interrupt(
            {
                "draft": note.model_dump(),
                "unsupported": [s.model_dump() for s in note.unsupported()],
                "removed": state.get("violations", []),
            }
        )
        return {"review": review}

    def commit(self, state: State) -> State:
        decision = ReviewDecision.model_validate(state["review"]["decision"])
        if decision.decision == "reject":
            return {"result": {"status": "rejected", "reason": decision.reason}}
        note = decision.edited or SoapNote.model_validate(state["note"])
        request = WriteFhirInput(
            resource=note_to_resource(note, state["patient_id"]),
            approval=state["review"]["approval"],
            identifiers=state["review"]["identifiers"],
        )
        try:
            written = self.tools.write(request)
        except ToolError as exc:
            return {"result": {"status": "write_refused", "reason": str(exc)}}
        edits = None
        if decision.edited is not None:
            edits = {"before": state["note"], "after": decision.edited.model_dump()}
        return {"result": {"status": "written", **written.model_dump(), "edit_pair": edits}}

    # ---------------------------------------------------------------- wiring
    def build(self, checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
        graph = StateGraph(State)
        for name in (
            "intake",
            "router",
            "ask_fast",
            "ask_agentic",
            "answer",
            "guardrail_answer",
            "note_writer",
            "guardrail_note",
            "hitl_review",
            "commit",
        ):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "intake")
        graph.add_conditional_edges("intake", self.after_intake, ["router", "note_writer", END])
        graph.add_conditional_edges(
            "router",
            lambda s: "ask_fast" if s["route"] == "fast" else "ask_agentic",
            ["ask_fast", "ask_agentic"],
        )
        graph.add_edge("ask_fast", "answer")
        graph.add_edge("ask_agentic", "answer")
        graph.add_edge("answer", "guardrail_answer")
        graph.add_conditional_edges(
            "guardrail_answer", self.after_guardrail_answer, ["answer", END]
        )
        graph.add_edge("note_writer", "guardrail_note")
        graph.add_conditional_edges(
            "guardrail_note", self.after_guardrail_note, ["note_writer", "hitl_review", END]
        )
        graph.add_edge("hitl_review", "commit")
        graph.add_edge("commit", END)
        return graph.compile(checkpointer=checkpointer)
