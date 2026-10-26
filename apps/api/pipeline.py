"""Phase 1 pipeline: text -> de-ID -> gateway -> audit record (PROGRESS task 9).

The answer stays in surrogate form (a development endpoint; the doctor-facing routes in
apps/api/clinical.py re-identify, ADR-0015). Text is never logged or put on spans.
"""

from dataclasses import dataclass
from typing import Protocol

from opentelemetry import trace

from apps.api.audit import AuditEntry
from llmops.gateway.client import ChatMessage, Completion, for_encounter
from llmops.prompts import Prompt
from privacy.deid.client import DeidOutput
from privacy.deid.types import DeidentifiedText


class Deid(Protocol):
    def deidentify(self, text: str, encounter_id: str) -> DeidOutput: ...


class Gateway(Protocol):
    def complete(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> Completion: ...


class Audit(Protocol):
    def append(self, entry: AuditEntry) -> int: ...


@dataclass(frozen=True)
class PipelineResult:
    text: str
    model: str
    prompt_version: str
    trace_id: str
    audit_seq: int
    replaced: dict[str, int]


class Pipeline:
    def __init__(
        self, deid: Deid, gateway: Gateway, audit: Audit, prompt: Prompt, alias: str
    ) -> None:
        self._deid = deid
        self._gateway = gateway
        self._audit = audit
        self._prompt = prompt
        self._alias = alias

    def run(self, text: str, encounter_id: str, actor: str) -> PipelineResult:
        span = trace.get_current_span()
        span.set_attribute("clinscribe.encounter_id", encounter_id)
        span.set_attribute("clinscribe.prompt_version", self._prompt.tag)
        trace_id = format(span.get_span_context().trace_id, "032x")

        deid = self._deid.deidentify(text, encounter_id)
        user: DeidentifiedText = deid.text
        with for_encounter(encounter_id):
            completion = self._gateway.complete(
                self._alias,
                [ChatMessage("system", self._prompt.system), ChatMessage("user", user)],
                temperature=self._prompt.temperature,
                max_tokens=self._prompt.max_tokens,
            )
        seq = self._audit.append(
            AuditEntry(
                actor=actor,
                role="operator",
                action="llm.complete",
                resource_type="dev_complete",
                encounter_id=encounter_id,
                model=completion.model,
                prompt_version=self._prompt.tag,
                trace_id=trace_id,
                details={
                    "gateway_alias": self._alias,
                    "response_id": completion.response_id,
                    "input_tokens": completion.input_tokens,
                    "output_tokens": completion.output_tokens,
                    "latency_ms": completion.latency_ms,
                    "phi_replaced": deid.replaced,
                },
            )
        )
        return PipelineResult(
            text=completion.text,
            model=completion.model,
            prompt_version=self._prompt.tag,
            trace_id=trace_id,
            audit_seq=seq,
            replaced=deid.replaced,
        )
