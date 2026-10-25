"""Typed contracts for agents and their tools (SPEC section 5; Phase 3 task 1).

Every MCP tool takes and returns one of these models, and every agent output is one of them,
re-validated in code after the provider's structured-output mode. Rules that matter for safety
live in the models themselves, so they hold wherever a model is built:
- a note statement must come from the transcript or carry a citation (or both);
- an answer sentence must cite at least one source;
- a patient summary carries the minimum necessary (no name, no date of birth, no address);
- a FHIR write request must carry an approval token and two patient identifiers.
The lab-report tool (`parse_lab_report`) is Phase 5 and gets its contract then.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# corpus chunk ids ("fda:<set id>#s4#c2") and graph facts ("graph:ddinter:valproic acid|aspirin")
ChunkId = Annotated[str, Field(min_length=1, pattern=r"^(who|fda|pmc|graph):[^\n]+$")]
Severity = Literal["Major", "Moderate", "Minor", "Unknown"]
Mode = Literal["scribe", "ask", "lab"]
# fhir-mcp's refusal when the doctor's two identifiers do not match the record. The graph keeps the
# draft open for corrected identifiers on this refusal only (a typo should not cost a new draft).
IDENTITY_MISMATCH = "patient identifiers do not match the record"
Role = Literal["doctor", "admin", "operator"]
SoapSection = Literal["subjective", "objective", "assessment", "plan"]


class Contract(BaseModel):
    """Strict base: unknown fields are errors, so a model reply with extra keys fails validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# --- search_guidelines (guidelines-mcp)
class SourceFilter(Contract):
    sources: list[Literal["who", "openfda", "pmc"]] | None = None
    topics: list[str] | None = None


class SearchGuidelinesInput(Contract):
    query: str = Field(min_length=3, max_length=500)  # de-identified text only (ADR-0001)
    k: int = Field(default=5, ge=1, le=20)
    filters: SourceFilter | None = None


class CheckGroundingInput(Contract):
    question: str = Field(min_length=3, max_length=2000)  # de-identified text only
    cited: list[ChunkId] = Field(default=[], max_length=40)  # an answer's citations


class GroundingReport(Contract):
    """Is the question's subject in the sources (ADR-0018)?"""

    unseen_terms: list[str] = []  # question words the corpus never uses, not English
    missing_drugs: list[str] = []  # drugs the question names that no cited source names


class Evidence(Contract):
    chunk_id: ChunkId
    text: str = Field(min_length=1)
    title: str
    section: str
    source: Literal["who", "openfda", "pmc", "ddinter"]
    source_url: str = Field(pattern=r"^https://")
    score: float


# --- check_interactions (druggraph-mcp)
class CheckInteractionsInput(Contract):
    drugs: list[str] = Field(min_length=2, max_length=10)


class Interaction(Contract):
    drug_a: str
    drug_b: str
    severity: Severity
    source: Literal["DDInter 2.0"] = "DDInter 2.0"
    source_id: ChunkId  # "graph:ddinter:A|B", citable like a chunk

    @model_validator(mode="after")
    def _pair_is_two_drugs(self) -> "Interaction":
        if self.drug_a.lower() == self.drug_b.lower():
            raise ValueError("an interaction needs two different drugs")
        return self


class InteractionReport(Contract):
    """Pairs found, and the names that matched no drug in the graph: "no interaction found" must
    never hide "drug unknown" (dabigatran, for example, is not in DDInter)."""

    interactions: list[Interaction]
    unknown_drugs: list[str] = []


# --- get_patient_context (fhir-mcp)
class GetPatientContextInput(Contract):
    patient_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9\-.]+$")
    # the authenticated user the agent acts for; every read is audited with it (task 9 adds auth)
    requested_by: str = Field(min_length=1)
    role: Role


class CodedItem(Contract):
    code: str | None = None  # SNOMED CT / RxNorm / LOINC code when the record has one
    display: str


class PatientSummary(Contract):
    """Minimum necessary context (HIPAA): no name, birth date, address or identifiers beyond the
    FHIR id. Age is in whole years and capped at 90 (Safe Harbor)."""

    patient_id: str
    age_years: int = Field(ge=0, le=90)
    sex: Literal["female", "male", "other", "unknown"]
    conditions: list[CodedItem] = []
    medications: list[CodedItem] = []
    allergies: list[CodedItem] = []


# --- write_fhir (fhir-mcp)
class PatientIdentifiers(Contract):
    """Two identifiers, checked against the FHIR record before any write (wrong-patient control)."""

    patient_id: str = Field(min_length=1)
    birth_date: date
    family_name: str = Field(min_length=1)


class ApprovalClaims(Contract):
    """What a doctor's approval binds: this draft, exactly this content, this patient, this person,
    for a short time. Signed with HMAC in task 8; the signature travels next to the claims."""

    draft_id: str = Field(min_length=1)
    draft_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    patient_id: str = Field(min_length=1)
    approver: str = Field(min_length=1)
    role: Literal["doctor"] = "doctor"  # only a doctor can approve a clinical write
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _expiry_after_issue(self) -> "ApprovalClaims":
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        return self


class ApprovalToken(Contract):
    claims: ApprovalClaims
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")  # hex HMAC-SHA-256


class WriteFhirInput(Contract):
    resource: dict[str, Any]
    approval: ApprovalToken
    identifiers: PatientIdentifiers

    @model_validator(mode="after")
    def _same_patient_everywhere(self) -> "WriteFhirInput":
        if self.approval.claims.patient_id != self.identifiers.patient_id:
            raise ValueError("approval and identifiers name different patients")
        if "resourceType" not in self.resource:
            raise ValueError("resource needs a resourceType")
        return self


class WriteFhirResult(Contract):
    resource_type: str
    resource_id: str


# --- agent outputs
class Utterance(Contract):
    index: int = Field(ge=0)
    speaker: Literal["doctor", "patient", "unknown"]
    text: str


class NoteStatement(Contract):
    section: SoapSection
    text: str = Field(min_length=1, max_length=600)
    transcript_turns: list[int] = []  # utterance indexes the statement came from
    citations: list[ChunkId] = []  # guideline chunks that support it

    @model_validator(mode="after")
    def _grounded(self) -> "NoteStatement":
        if not self.transcript_turns and not self.citations:
            raise ValueError("a statement needs transcript turns or citations")
        return self


class SoapNote(Contract):
    encounter_id: str
    statements: list[NoteStatement] = Field(min_length=1)
    ai_generated: Literal[True] = True  # EU AI Act transparency: every draft is labelled
    prompt_version: str
    model: str

    def unsupported(self) -> list[NoteStatement]:
        """Assessment and plan statements without a citation: highlighted for the doctor."""
        return [
            s for s in self.statements if s.section in ("assessment", "plan") and not s.citations
        ]


class AnswerSentence(Contract):
    text: str = Field(min_length=1)
    citations: list[ChunkId] = Field(min_length=1)


class AskAnswer(Contract):
    question_id: str
    abstained: bool
    sentences: list[AnswerSentence] = []
    path: Literal["fast", "agentic"]
    prompt_version: str
    model: str

    @model_validator(mode="after")
    def _abstain_xor_sentences(self) -> "AskAnswer":
        if self.abstained == bool(self.sentences):
            raise ValueError("an answer either abstains or has sentences, not both or neither")
        return self


class ReviewDecision(Contract):
    draft_id: str
    decision: Literal["approve", "edit", "reject"]
    reviewer: str
    edited: SoapNote | None = None  # the doctor's version when decision == "edit"
    reason: str | None = None

    @model_validator(mode="after")
    def _edit_has_note(self) -> "ReviewDecision":
        if (self.decision == "edit") != (self.edited is not None):
            raise ValueError("an edit carries the edited note, and only an edit does")
        if self.decision == "reject" and not self.reason:
            raise ValueError("a rejection needs a reason")
        return self


# --- parse_lab_report (fhir-mcp; Phase 5)
class ParseLabReportInput(Contract):
    pdf_base64: str = Field(min_length=10, max_length=7_000_000)  # ~5 MB PDF
    patient_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9\-.]+$")
    requested_by: str = Field(min_length=1)
    role: Role


class LabParseResult(Contract):
    """Parsed values pending the doctor's confirmation; nothing is written by this tool."""

    observations: list[dict[str, Any]]  # preliminary FHIR Observations for known tests
    abnormal: list[str]  # "Potassium 5.6 mmol/L (H)"
    not_mapped: list[str]  # rows read but not mapped (unknown test or unexpected unit)
    unreadable_rows: list[str]
    identity: dict[str, bool]  # name / birth_date on the report match the record
    collected: str | None
