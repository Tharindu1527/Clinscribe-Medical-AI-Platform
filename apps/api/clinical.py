"""Clinical endpoints (Phase 3 tasks 8-9): Ask, Scribe drafts, the doctor's review, the audit log.

Everything a model sees is de-identified first (the de-ID service), every action is audited, and a
clinical write happens only after a doctor's review: the API signs an approval token for the exact
FHIR resource the reviewed note becomes, and fhir-mcp verifies it again before writing.
Doctors see the originals (`?identified=true`), and the record holds them (ADR-0015): the API
re-identifies through the de-ID service, audits every disclosure, and de-identifies the doctor's
edits again before they go back into the graph.
Drafts awaiting review are checkpointed in Postgres and listed in the `drafts` table, so they
survive a restart; the PHI a write needs is passed as run context, never checkpointed, and a
draft's checkpoints are deleted when it ends (ADR-0016).
"""

import hmac
import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Annotated, Any, Literal

import httpx
import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel, Field, model_validator

from agents.approval import approve
from agents.fhir_docs import note_to_resource
from agents.graph import WriteContext
from agents.schemas import ReviewDecision, SoapNote
from apps.api.audit import AuditEntry
from apps.api.auth import Principal, issue_token, require, users
from apps.api.drafts import WAITING, Draft
from apps.api.voice_token import room_token
from config.db import app_conninfo
from config.settings import Settings
from llmops.gateway.client import for_encounter

router = APIRouter(prefix="/v1")
log = logging.getLogger(__name__)
ID = r"^[A-Za-z0-9._-]{1,64}$"
Doctor = Annotated[Principal, Depends(require("doctor"))]


class LoginRequest(BaseModel):
    user: str = Field(pattern=ID)


class AskRequest(BaseModel):
    encounter_id: str = Field(pattern=ID)
    question: str = Field(min_length=3, max_length=2000)


class Turn(BaseModel):
    speaker: Literal["doctor", "patient", "unknown"]
    text: str = Field(min_length=1, max_length=4000)


class DraftRequest(BaseModel):
    encounter_id: str = Field(pattern=ID)
    patient_id: str = Field(pattern=ID)
    transcript: list[Turn] = Field(min_length=1, max_length=400)


class ReviewRequest(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    edited: SoapNote | None = None
    reason: str | None = None
    birth_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    family_name: str | None = None
    edited_identified: bool = False  # the edits were typed on the re-identified view (ADR-0015)


def _audit(request: Request, who: Principal, action: str, **fields: Any) -> int:
    seq: int = request.app.state.audit.append(
        AuditEntry(actor=who.user, role=who.role, action=action, **fields)
    )
    return seq


def _config(thread: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread}}


def _reidentify(
    request: Request, who: Principal, encounter_id: str, texts: list[str], context: str, ref: str
) -> list[str]:
    """Originals for the doctor's screen or the approved record (ADR-0015). Every call that restores
    anything is audited, with counts only, never the text."""
    out = request.app.state.deid.reidentify(texts, encounter_id)
    if out.restored:
        _audit(
            request,
            who,
            "phi.reidentify",
            resource_id=ref,
            encounter_id=encounter_id,
            details={"context": context, "texts": len(texts), "restored": out.restored},
        )
    texts_out: list[str] = out.texts
    return texts_out


def _with_texts(note: SoapNote, texts: list[str]) -> SoapNote:
    statements = [
        s.model_copy(update={"text": t}) for s, t in zip(note.statements, texts, strict=True)
    ]
    return note.model_copy(update={"statements": statements})


def _identified_draft(
    request: Request, who: Principal, draft_id: str, encounter_id: str, payload: dict[str, Any]
) -> dict[str, list[str]]:
    transcript = list(payload["transcript"])
    statements = [s["text"] for s in payload["draft"]["statements"]]
    texts = _reidentify(request, who, encounter_id, transcript + statements, "draft", draft_id)
    return {"transcript": texts[: len(transcript)], "statements": texts[len(transcript) :]}


def _run(step: Callable[[], Any], encounter_id: str) -> Any:
    """Run a graph step; its model calls are tagged with the encounter (cost per consultation,
    ADR-0023); model-gateway failures become 504/502 with a message, not a bare 500."""
    try:
        with for_encounter(encounter_id):
            return step()
    except httpx.TimeoutException:
        log.warning("model gateway timeout")
        raise HTTPException(504, "the model gateway timed out; please try again") from None
    except httpx.HTTPError as exc:
        # status and type only: provider error text can echo (de-identified) prompt content
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        log.warning("model gateway failure: %s status=%s", type(exc).__name__, status)
        raise HTTPException(502, f"the model gateway failed: {type(exc).__name__}") from None


@router.post("/dev/login")
def dev_login(body: LoginRequest) -> dict[str, str]:
    """Token for a synthetic demo user; enabled only with DEV_LOGIN=true (local demo)."""
    settings = Settings()
    if not settings.dev_login:
        raise HTTPException(404, "not found")
    if body.user not in users():
        raise HTTPException(403, "unknown user")
    return {"token": issue_token(body.user, settings.auth_token_key), "role": users()[body.user]}


@router.post("/ask")
def ask(
    body: AskRequest, request: Request, who: Doctor, identified: bool = False
) -> dict[str, Any]:
    deid = request.app.state.deid.deidentify(body.question, body.encounter_id)
    thread = f"ask-{uuid.uuid4().hex}"
    out = _run(
        lambda: request.app.state.ask_graph.invoke(
            {"mode": "ask", "encounter_id": body.encounter_id, "question": deid.text.text},
            _config(thread),
        ),
        body.encounter_id,
    )
    if out.get("result", {}).get("status") == "refused":
        raise HTTPException(422, out["result"]["reason"])
    answer = out["answer"]
    evidence = [
        {k: e[k] for k in ("chunk_id", "title", "section", "source", "source_url", "text")}
        for e in out.get("evidence", [])
    ]
    _audit(
        request,
        who,
        "ask",
        encounter_id=body.encounter_id,
        model=answer["model"],
        prompt_version=answer["prompt_version"],
        details={
            "route": out["route"],
            "abstained": answer["abstained"],
            "violations": len(out.get("violations", [])),
            "phi_replaced": deid.replaced,
        },
    )
    response = {
        "answer": answer,
        "evidence": evidence,
        "route": out["route"],
        "violations": out.get("violations", []),
        "dropped": out.get("dropped", []),
        "events": out.get("events", []),
        "unseen_terms": out.get("unseen", []),  # words no source uses: the answer abstained
        "ai_generated": True,
    }
    if identified:
        texts = [s["text"] for s in answer["sentences"]]
        sentences = _reidentify(request, who, body.encounter_id, texts, "answer", thread)
        response["identified"] = {"sentences": sentences}
    return response


@router.post("/scribe/drafts")
def create_draft(
    body: DraftRequest, request: Request, who: Doctor, identified: bool = False
) -> dict[str, Any]:
    deid = request.app.state.deid
    turns = [
        f"{t.speaker.upper()}: {deid.deidentify(t.text, body.encounter_id).text.text}"
        for t in body.transcript
    ]
    draft_id = f"draft-{uuid.uuid4().hex[:16]}"
    out = _run(
        lambda: request.app.state.graph.invoke(
            {
                "mode": "scribe",
                "encounter_id": body.encounter_id,
                "patient_id": body.patient_id,
                "transcript": turns,
            },
            _config(draft_id),
        ),
        body.encounter_id,
    )
    if "__interrupt__" not in out:
        raise HTTPException(422, (out.get("result") or {}).get("reason", "no draft produced"))
    payload = out["__interrupt__"][0].value
    request.app.state.drafts.add(Draft(draft_id, body.patient_id, body.encounter_id, who.user))
    _audit(
        request,
        who,
        "draft.create",
        resource_type="DocumentReference",
        resource_id=draft_id,
        encounter_id=body.encounter_id,
        model=payload["draft"]["model"],
        prompt_version=payload["draft"]["prompt_version"],
        details={
            "statements": len(payload["draft"]["statements"]),
            "unsupported": len(payload["unsupported"]),
            "removed": len(payload["removed"]),
        },
    )
    response = {"draft_id": draft_id, "transcript": turns, **payload}
    if identified:
        response["identified"] = _identified_draft(
            request, who, draft_id, body.encounter_id, response
        )
    return response


@router.get("/drafts")
def list_drafts(request: Request, who: Doctor) -> list[dict[str, Any]]:
    """Drafts awaiting a doctor's review, newest first (e.g. made by the Scribe audio listener)."""
    waiting = []
    for draft in request.app.state.drafts.waiting():
        state = request.app.state.graph.get_state(_config(draft.draft_id))
        if any(task.interrupts for task in state.tasks):
            note = state.values.get("note") or {}
            waiting.append(
                {
                    "draft_id": draft.draft_id,
                    "patient_id": draft.patient_id,
                    "created_by": draft.created_by,
                    "statements": len(note.get("statements", [])),
                }
            )
    return waiting


@router.get("/drafts/{draft_id}")
def get_draft(
    draft_id: str, request: Request, who: Doctor, identified: bool = False
) -> dict[str, Any]:
    draft = request.app.state.drafts.get(draft_id)
    if draft is None:
        raise HTTPException(404, "no such draft")
    if draft.status != WAITING:  # ended: its checkpoints are gone, the outcome is recorded
        result = {"status": draft.status, "resource_id": draft.resource_id}
        return {"draft_id": draft_id, "status": "done", "result": result}
    state = request.app.state.graph.get_state(_config(draft_id))
    pending = [i.value for task in state.tasks for i in task.interrupts]
    if not pending:
        raise HTTPException(410, "the draft's saved state is gone")
    transcript = state.values.get("transcript", [])
    response = {
        "draft_id": draft_id,
        "status": "awaiting_review",
        "transcript": transcript,
        **pending[0],
    }
    if identified:
        encounter_id = state.values["encounter_id"]
        response["identified"] = _identified_draft(request, who, draft_id, encounter_id, response)
    return response


@router.post("/drafts/{draft_id}/review")
def review(draft_id: str, body: ReviewRequest, request: Request, who: Doctor) -> dict[str, Any]:
    meta = request.app.state.drafts.get(draft_id)
    if meta is None:
        raise HTTPException(404, "no such draft")
    if meta.status != WAITING:
        raise HTTPException(409, "draft is not awaiting review")
    graph = request.app.state.graph
    state = graph.get_state(_config(draft_id))
    if not state.tasks or not any(t.interrupts for t in state.tasks):
        raise HTTPException(409, "draft is not awaiting review")
    try:
        decision = ReviewDecision(
            draft_id=draft_id,
            decision=body.decision,
            reviewer=who.user,
            edited=body.edited,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    resume: dict[str, Any] = {}
    context: WriteContext | None = None
    if body.decision != "reject":
        if not (body.birth_date and body.family_name):
            raise HTTPException(422, "approval needs the patient's birth date and family name")
        encounter_id = state.values["encounter_id"]
        if body.edited is not None and body.edited_identified:
            # the doctor's words go to the record; the graph keeps them in surrogate form
            record = body.edited
            deid = request.app.state.deid
            texts = [
                deid.deidentify(s.text, encounter_id).text.text for s in body.edited.statements
            ]
            decision = decision.model_copy(update={"edited": _with_texts(body.edited, texts)})
        else:
            note = body.edited or SoapNote.model_validate(state.values["note"])
            texts = [s.text for s in note.statements]
            record = _with_texts(
                note, _reidentify(request, who, encounter_id, texts, "record", draft_id)
            )
        # the approval covers exactly what is written: the note as the doctor read it (ADR-0015)
        resource = note_to_resource(record, meta.patient_id)
        token = approve(
            draft_id, resource, meta.patient_id, who.user, Settings().approval_token_key
        )
        resume["approval"] = token.model_dump(mode="json")
        # PHI for the write only: run context is never checkpointed (ADR-0016)
        context = WriteContext(
            identifiers={
                "patient_id": meta.patient_id,
                "birth_date": body.birth_date,
                "family_name": body.family_name,
            },
            resource=resource,
        )
    resume["decision"] = decision.model_dump(mode="json")
    out = _run(
        lambda: graph.invoke(Command(resume=resume), _config(draft_id), context=context),
        meta.encounter_id,
    )
    result = out.get("result", {})
    if not out.get("__interrupt__"):  # the draft ended: keep the outcome, drop its state
        request.app.state.drafts.finish(draft_id, result.get("status"), result.get("resource_id"))
        request.app.state.checkpointer.delete_thread(draft_id)
    _audit(
        request,
        who,
        f"draft.{body.decision}",
        resource_type="DocumentReference",
        resource_id=result.get("resource_id") or draft_id,
        details={
            "draft_id": draft_id,
            "status": result.get("status"),
            "edited": body.decision == "edit",
        },
    )
    response: dict[str, Any] = {"draft_id": draft_id, "result": result}
    if pending := out.get("__interrupt__"):  # wrong identifiers: the draft is still open
        response |= {"awaiting_review": True, "attempts_left": pending[0].value["attempts_left"]}
    return response


@router.post("/voice/token")
def voice_token(request: Request, who: Doctor) -> dict[str, str]:
    """A LiveKit room for one browser voice session (ADR-0019). The voice agent worker joins every
    new room; the doctor's audio goes to the self-hosted LiveKit server, then Deepgram."""
    settings = Settings()
    room = f"clinscribe-{who.user}-{uuid.uuid4().hex[:8]}"
    token = room_token(settings.livekit_api_key, settings.livekit_api_secret, who.user, room)
    _audit(request, who, "voice.session", resource_type="Room", resource_id=room)
    return {"url": settings.livekit_url, "room": room, "token": token}


class DelegateRequest(BaseModel):
    room: str = Field(pattern=r"^clinscribe-[A-Za-z0-9._-]{1,64}-[0-9a-f]{8}$")
    user: str = Field(pattern=ID)


@router.post("/voice/delegate")
def voice_delegate(
    body: DelegateRequest, request: Request, x_voice_agent_key: Annotated[str, Header()] = ""
) -> dict[str, str]:
    """The voice agent acts for the doctor in its room (ADR-0019): a 30-minute token for that
    doctor, so voice questions are audited as the doctor who asked them. Only the worker holds
    VOICE_AGENT_KEY; LiveKit verified the participant against the room token this API issued,
    whose room name carries the doctor's user name."""
    settings = Settings()
    expected = settings.voice_agent_key.get_secret_value()
    if not expected or not hmac.compare_digest(x_voice_agent_key.encode(), expected.encode()):
        raise HTTPException(403, "only the voice agent may ask")
    if users().get(body.user) != "doctor" or not body.room.startswith(f"clinscribe-{body.user}-"):
        raise HTTPException(403, "the room was not issued to this doctor")
    who = Principal(user=body.user, role="doctor")
    _audit(request, who, "voice.delegate", resource_type="Room", resource_id=body.room)
    token = issue_token(body.user, settings.auth_token_key, ttl=timedelta(minutes=30))
    return {"token": token}


@router.get("/audit")
def audit_log(
    who: Annotated[Principal, Depends(require("admin", "operator"))], limit: int = 50
) -> list[dict[str, Any]]:
    """Recent audit rows: who did what, when, with which model and prompt version (SPEC story 5)."""
    columns = (
        "seq",
        "ts",
        "actor",
        "role",
        "action",
        "resource_type",
        "resource_id",
        "encounter_id",
        "model",
        "prompt_version",
    )
    with psycopg.connect(app_conninfo(Settings()), connect_timeout=10) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM audit_log ORDER BY seq DESC LIMIT %s",  # noqa: S608
            (min(max(limit, 1), 500),),
        ).fetchall()
    return [
        dict(zip(columns, (str(v) if v is not None else None for v in row), strict=True))
        for row in rows
    ]


class LabParseRequest(BaseModel):
    """A lab-report PDF, or an HL7 v2 ORU^R01 message (ADR-0021)."""

    patient_id: str = Field(pattern=ID)
    pdf_base64: str | None = Field(default=None, min_length=10, max_length=7_000_000)
    hl7_message: str | None = Field(default=None, min_length=10, max_length=200_000)

    @model_validator(mode="after")
    def _one_report(self) -> "LabParseRequest":
        if (self.pdf_base64 is None) == (self.hl7_message is None):
            raise ValueError("give exactly one of pdf_base64 and hl7_message")
        return self


class LabConfirmRequest(BaseModel):
    birth_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    family_name: str = Field(min_length=1)
    indexes: list[int] | None = None  # which parsed values the doctor confirms; None = all


@router.post("/lab/parse")
def lab_parse(body: LabParseRequest, request: Request, who: Doctor) -> dict[str, Any]:
    """Lab-report PDF or HL7 v2 ORU^R01 message -> preliminary Observations with flags, pending
    the doctor's confirmation."""
    from agents.schemas import ParseLabReportInput
    from agents.tools import ToolError

    try:
        parsed = request.app.state.tools.parse_lab(
            ParseLabReportInput(
                pdf_base64=body.pdf_base64,
                hl7_message=body.hl7_message,
                patient_id=body.patient_id,
                requested_by=who.user,
                role=who.role,
            )
        )
    except ToolError as exc:
        raise HTTPException(422, str(exc)) from None
    lab_id = f"lab-{uuid.uuid4().hex[:16]}"
    request.app.state.labs[lab_id] = {"patient_id": body.patient_id, **parsed.model_dump()}
    return {"lab_id": lab_id, **parsed.model_dump()}


@router.post("/lab/{lab_id}/confirm")
def lab_confirm(
    lab_id: str, body: LabConfirmRequest, request: Request, who: Doctor
) -> dict[str, Any]:
    """Writes the confirmed Observations (final), each with its own approval for exact content."""
    from agents.schemas import PatientIdentifiers, WriteFhirInput
    from agents.tools import ToolError

    pending = request.app.state.labs.get(lab_id)
    if pending is None:
        raise HTTPException(404, "no such lab report")
    if not all(pending["identity"].values()):
        raise HTTPException(409, f"report does not match the patient record: {pending['identity']}")
    chosen = range(len(pending["observations"])) if body.indexes is None else body.indexes
    identifiers = PatientIdentifiers.model_validate(
        {
            "patient_id": pending["patient_id"],
            "birth_date": body.birth_date,
            "family_name": body.family_name,
        }
    )
    written, refused = [], []
    for index in chosen:
        if not 0 <= index < len(pending["observations"]):
            raise HTTPException(422, f"no parsed value {index}")
        resource = {**pending["observations"][index], "status": "final"}
        token = approve(
            f"{lab_id}-{index}",
            resource,
            pending["patient_id"],
            who.user,
            Settings().approval_token_key,
        )
        try:
            result = request.app.state.tools.write(
                WriteFhirInput(resource=resource, approval=token, identifiers=identifiers)
            )
            written.append(result.resource_id)
        except ToolError as exc:
            refused.append(f"{index}: {exc}")
    _audit(
        request,
        who,
        "lab.confirm",
        resource_type="Observation",
        resource_id=lab_id,
        details={"written": len(written), "refused": len(refused)},
    )
    request.app.state.labs.pop(lab_id, None)
    return {"lab_id": lab_id, "written": written, "refused": refused}
