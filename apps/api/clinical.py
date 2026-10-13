"""Clinical endpoints (Phase 3 tasks 8-9): Ask, Scribe drafts, the doctor's review, the audit log.

Everything a model sees is de-identified first (the de-ID service), every action is audited, and a
clinical write happens only after a doctor's review: the API signs an approval token for the exact
FHIR resource the reviewed note becomes, and fhir-mcp verifies it again before writing.
Drafts live in the graph's checkpointer (in memory: a restart drops pending drafts; see PROGRESS).
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

import httpx
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel, Field

from agents.approval import approve
from agents.fhir_docs import note_to_resource
from agents.schemas import ReviewDecision, SoapNote
from apps.api.audit import AuditEntry
from apps.api.auth import Principal, issue_token, require, users
from config.db import app_conninfo
from config.settings import Settings

router = APIRouter(prefix="/v1")
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


def _audit(request: Request, who: Principal, action: str, **fields: Any) -> int:
    seq: int = request.app.state.audit.append(
        AuditEntry(actor=who.user, role=who.role, action=action, **fields)
    )
    return seq


def _config(thread: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread}}


def _run(step: Callable[[], Any]) -> Any:
    """Run a graph step; model-gateway failures become 504/502 with a message, not a bare 500."""
    try:
        return step()
    except httpx.TimeoutException:
        raise HTTPException(504, "the model gateway timed out; please try again") from None
    except httpx.HTTPError as exc:
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
def ask(body: AskRequest, request: Request, who: Doctor) -> dict[str, Any]:
    deid = request.app.state.deid.deidentify(body.question, body.encounter_id)
    out = _run(
        lambda: request.app.state.graph.invoke(
            {"mode": "ask", "encounter_id": body.encounter_id, "question": deid.text.text},
            _config(f"ask-{uuid.uuid4().hex}"),
        )
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
    return {
        "answer": answer,
        "evidence": evidence,
        "route": out["route"],
        "violations": out.get("violations", []),
        "dropped": out.get("dropped", []),
        "events": out.get("events", []),
        "ai_generated": True,
    }


@router.post("/scribe/drafts")
def create_draft(body: DraftRequest, request: Request, who: Doctor) -> dict[str, Any]:
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
        )
    )
    if "__interrupt__" not in out:
        raise HTTPException(422, (out.get("result") or {}).get("reason", "no draft produced"))
    payload = out["__interrupt__"][0].value
    request.app.state.drafts[draft_id] = {"patient_id": body.patient_id, "created_by": who.user}
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
    return {"draft_id": draft_id, "transcript": turns, **payload}


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: str, request: Request, who: Doctor) -> dict[str, Any]:
    if draft_id not in request.app.state.drafts:
        raise HTTPException(404, "no such draft")
    state = request.app.state.graph.get_state(_config(draft_id))
    pending = [i.value for task in state.tasks for i in task.interrupts]
    if not pending:
        return {"draft_id": draft_id, "status": "done", "result": state.values.get("result")}
    return {"draft_id": draft_id, "status": "awaiting_review", **pending[0]}


@router.post("/drafts/{draft_id}/review")
def review(draft_id: str, body: ReviewRequest, request: Request, who: Doctor) -> dict[str, Any]:
    meta = request.app.state.drafts.get(draft_id)
    if meta is None:
        raise HTTPException(404, "no such draft")
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
    resume: dict[str, Any] = {"decision": decision.model_dump(mode="json")}
    if body.decision != "reject":
        if not (body.birth_date and body.family_name):
            raise HTTPException(422, "approval needs the patient's birth date and family name")
        note = body.edited or SoapNote.model_validate(state.values["note"])
        resource = note_to_resource(note, meta["patient_id"])
        token = approve(
            draft_id, resource, meta["patient_id"], who.user, Settings().approval_token_key
        )
        resume |= {
            "approval": token.model_dump(mode="json"),
            "identifiers": {
                "patient_id": meta["patient_id"],
                "birth_date": body.birth_date,
                "family_name": body.family_name,
            },
        }
    out = _run(lambda: graph.invoke(Command(resume=resume), _config(draft_id)))
    result = out.get("result", {})
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
    return {"draft_id": draft_id, "result": result}


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
