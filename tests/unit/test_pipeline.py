"""Pipeline wiring with fakes: the LLM sees only de-identified text, and every call is audited."""

from collections.abc import Sequence

import httpx

from apps.api.audit import AuditEntry
from apps.api.pipeline import Pipeline
from llmops.gateway.client import ChatMessage, Completion
from llmops.prompts import load_prompt
from privacy.deid.client import DeidClient, DeidOutput
from privacy.deid.types import DeidentifiedText, issue

RAW = "MRN 00482913, call 617-555-0142 about the rash."
MASKED = "MRN MRN_1, call PHONE_1 about the rash."


class FakeDeid:
    def deidentify(self, text: str, encounter_id: str) -> DeidOutput:
        assert text == RAW
        return DeidOutput(issue(MASKED, source="deid-service"), {"MRN": 1, "PHONE": 1})


class FakeGateway:
    def __init__(self) -> None:
        self.seen: list[ChatMessage] = []

    def complete(
        self,
        model: str,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> Completion:
        self.seen = list(messages)
        return Completion("Noted for MRN_1.", "gemini/test", 30, 6, 12.0, response_id="chatcmpl-x")


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def append(self, entry: AuditEntry) -> int:
        self.entries.append(entry)
        return 41


def test_pipeline_sends_only_deidentified_text_and_audits() -> None:
    gateway, audit = FakeGateway(), FakeAudit()
    prompt = load_prompt("dev_complete")
    result = Pipeline(FakeDeid(), gateway, audit, prompt, "clinscribe-default").run(
        RAW, "enc-1", actor="tester"
    )

    assert all(isinstance(m.content, DeidentifiedText) for m in gateway.seen)
    assert gateway.seen[1].content.text == MASKED
    assert all("00482913" not in m.content.text for m in gateway.seen)

    (entry,) = audit.entries
    assert (entry.actor, entry.action, entry.encounter_id) == ("tester", "llm.complete", "enc-1")
    assert entry.prompt_version == "dev_complete@v1"
    assert entry.model == "gemini/test"
    assert entry.details["phi_replaced"] == {"MRN": 1, "PHONE": 1}
    assert "00482913" not in repr(entry)  # the audit record holds no PHI

    assert (result.text, result.audit_seq, result.prompt_version) == (
        "Noted for MRN_1.",
        41,
        "dev_complete@v1",
    )


def test_deid_client_counts_types_and_returns_deidentified_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "text": MASKED,
                "replacements": [
                    {"entity": "MRN", "surrogate": "MRN_1"},
                    {"entity": "PHONE", "surrogate": "PHONE_1"},
                ],
            },
        )

    out = DeidClient("http://deid", transport=httpx.MockTransport(handler)).deidentify(RAW, "enc-1")
    assert isinstance(out.text, DeidentifiedText)
    assert out.text.text == MASKED
    assert out.replaced == {"MRN": 1, "PHONE": 1}


def test_prompt_file_is_versioned() -> None:
    prompt = load_prompt("dev_complete")
    assert prompt.tag == "dev_complete@v1"
    assert prompt.task == "dev_complete"
    assert isinstance(prompt.system, DeidentifiedText)
