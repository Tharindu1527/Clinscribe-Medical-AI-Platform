"""Phase 3 task 1: agent and tool contracts enforce their safety rules wherever they are built."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from agents.schemas import (
    ApprovalClaims,
    ApprovalToken,
    AskAnswer,
    Evidence,
    Interaction,
    NoteStatement,
    PatientIdentifiers,
    PatientSummary,
    ReviewDecision,
    SearchGuidelinesInput,
    SoapNote,
    WriteFhirInput,
)

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _claims(**overrides: Any) -> ApprovalClaims:
    values: dict[str, Any] = {
        "draft_id": "draft-1",
        "draft_sha256": "a" * 64,
        "patient_id": "p-1",
        "approver": "dr-house",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
    } | overrides
    return ApprovalClaims(**values)


def _note(*statements: NoteStatement) -> SoapNote:
    return SoapNote(
        encounter_id="enc-1", statements=list(statements), prompt_version="p@v1", model="m"
    )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra"):
        SearchGuidelinesInput(query="warfarin dose", k=5, temperature=1)  # type: ignore[call-arg]


def test_evidence_needs_a_known_chunk_id_and_https_source() -> None:
    ok = Evidence(
        chunk_id="fda:abc#s4#c2",
        text="t",
        title="T",
        section="S",
        source="openfda",
        source_url="https://dailymed.nlm.nih.gov/x",
        score=0.5,
    )
    assert ok.chunk_id.startswith("fda:")
    with pytest.raises(ValidationError):
        Evidence(**(ok.model_dump() | {"chunk_id": "made-up-1"}))
    with pytest.raises(ValidationError):
        Evidence(**(ok.model_dump() | {"source_url": "http://insecure"}))


def test_interaction_is_between_two_different_drugs_and_cites_the_graph() -> None:
    fact = Interaction(
        drug_a="Warfarin",
        drug_b="Valproic acid",
        severity="Major",
        source_id="graph:ddinter:Valproic acid|Warfarin",
    )
    assert fact.source == "DDInter 2.0"
    with pytest.raises(ValidationError, match="two different drugs"):
        Interaction(drug_a="Warfarin", drug_b="warfarin", severity="Minor", source_id="graph:x")


def test_patient_summary_holds_the_minimum_necessary() -> None:
    assert "name" not in PatientSummary.model_fields
    assert "birth_date" not in PatientSummary.model_fields
    with pytest.raises(ValidationError):
        PatientSummary(patient_id="p-1", age_years=95, sex="female")  # Safe Harbor caps at 90
    with pytest.raises(ValidationError, match="extra"):
        PatientSummary(patient_id="p-1", age_years=40, sex="male", name="X")  # type: ignore[call-arg]


def test_note_statements_must_be_grounded_and_unsupported_ones_are_listed() -> None:
    with pytest.raises(ValidationError, match="transcript turns or citations"):
        NoteStatement(section="plan", text="Start metformin.")
    told = NoteStatement(section="subjective", text="Thirsty for 2 weeks.", transcript_turns=[3])
    guessed = NoteStatement(section="plan", text="Start metformin.", transcript_turns=[9])
    cited = NoteStatement(
        section="assessment",
        text="HbA1c above target.",
        transcript_turns=[7],
        citations=["who:10665-272433#s2#c1"],
    )
    note = _note(told, guessed, cited)
    assert note.ai_generated is True
    assert note.unsupported() == [guessed]


def test_answer_cites_every_sentence_and_abstains_explicitly() -> None:
    AskAnswer(question_id="q", abstained=True, path="fast", prompt_version="p@v1", model="m")
    with pytest.raises(ValidationError):
        AskAnswer(question_id="q", abstained=False, path="fast", prompt_version="p@v1", model="m")
    with pytest.raises(ValidationError):
        AskAnswer.model_validate(
            {
                "question_id": "q",
                "abstained": False,
                "path": "fast",
                "prompt_version": "p@v1",
                "model": "m",
                "sentences": [{"text": "Take 5 mg.", "citations": []}],
            }
        )


def test_approval_claims_are_short_lived_and_doctor_only() -> None:
    with pytest.raises(ValidationError, match="after issued_at"):
        _claims(expires_at=NOW)
    with pytest.raises(ValidationError):
        _claims(role="operator")
    with pytest.raises(ValidationError):
        _claims(draft_sha256="not-a-hash")


def test_write_needs_matching_patient_and_a_resource_type() -> None:
    token = ApprovalToken(claims=_claims(), signature="b" * 64)
    ids = PatientIdentifiers(patient_id="p-1", birth_date=date(1970, 1, 2), family_name="Doe")
    resource = {"resourceType": "DocumentReference", "status": "current"}
    WriteFhirInput(resource=resource, approval=token, identifiers=ids)
    with pytest.raises(ValidationError, match="different patients"):
        WriteFhirInput(
            resource=resource,
            approval=token,
            identifiers=ids.model_copy(update={"patient_id": "p-2"}),
        )
    with pytest.raises(ValidationError, match="resourceType"):
        WriteFhirInput(resource={"status": "current"}, approval=token, identifiers=ids)


def test_review_decision_shapes() -> None:
    note = _note(NoteStatement(section="subjective", text="Cough.", transcript_turns=[1]))
    ReviewDecision(draft_id="d", decision="approve", reviewer="dr")
    ReviewDecision(draft_id="d", decision="edit", reviewer="dr", edited=note)
    with pytest.raises(ValidationError, match="edited note"):
        ReviewDecision(draft_id="d", decision="edit", reviewer="dr")
    with pytest.raises(ValidationError, match="reason"):
        ReviewDecision(draft_id="d", decision="reject", reviewer="dr")
