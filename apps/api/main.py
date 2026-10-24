"""ClinScribe API. Phase 1: health and the pipeline smoke endpoint (de-ID -> LLM -> audit).
Phase 3: auth, Ask, Scribe drafts with the doctor's review, audit log (apps/api/clinical.py)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from agents.graph import Agents
from agents.tools import McpTools
from apps.api.audit import AuditLog
from apps.api.clinical import router as clinical
from apps.api.pipeline import Pipeline
from config.db import app_conninfo
from config.settings import Settings
from llmops.gateway.client import GatewayClient, alias_for
from llmops.prompts import load_prompt
from llmops.telemetry.setup import (
    FASTAPI_TELEMETRY,
    configure_logging,
    configure_tracing,
    instrument,
)
from privacy.deid.client import DeidClient

SERVICE = "api"
ID_PATTERN = r"^[A-Za-z0-9._-]{1,64}$"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging()
    provider = configure_tracing(SERVICE, settings.otel_exporter_otlp_endpoint)
    prompt = load_prompt("dev_complete")
    deid = DeidClient(
        settings.deid_url, reidentify_key=settings.deid_reidentify_key.get_secret_value()
    )
    # 300 s: a long note on the free tier takes up to ~3 min (ACI-Bench p95 179 s: 503s + fallback)
    gateway = GatewayClient(settings.gateway_url, settings.litellm_app_key, timeout=300.0)
    audit = AuditLog(app_conninfo(settings), settings.audit_chain_key)
    tools = McpTools(settings.guidelines_mcp_url, settings.druggraph_mcp_url, settings.fhir_mcp_url)
    app.state.deid = deid
    app.state.audit = audit
    app.state.graph = Agents(gateway, tools).build(InMemorySaver())
    app.state.tools = tools
    app.state.drafts = {}
    app.state.labs = {}
    app.state.pipeline = Pipeline(
        deid=deid,
        gateway=gateway,
        audit=audit,
        prompt=prompt,
        alias=alias_for(prompt.task),
    )
    yield
    deid.close()
    gateway.close()
    provider.shutdown()


app = FastAPI(
    title="ClinScribe API", version="0.1.0", lifespan=lifespan, telemetry=FASTAPI_TELEMETRY
)
instrument(app, SERVICE)
app.include_router(clinical)
app.add_middleware(  # the review UI's dev server (apps/web)
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


class CompleteRequest(BaseModel):
    encounter_id: str = Field(pattern=ID_PATTERN)
    text: str = Field(min_length=1, max_length=20_000)


class CompleteResponse(BaseModel):
    text: str  # surrogate form (dev endpoint; the doctor's views re-identify, ADR-0015)
    model: str
    prompt_version: str
    trace_id: str
    audit_seq: int
    phi_replaced: dict[str, int]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE}


@app.post("/v1/dev/complete")
def dev_complete(
    request: CompleteRequest,
    x_actor: str = Header(default="dev", pattern=ID_PATTERN),  # real identity arrives with auth
) -> CompleteResponse:
    pipeline: Pipeline = app.state.pipeline
    result = pipeline.run(request.text, request.encounter_id, actor=x_actor)
    return CompleteResponse(
        text=result.text,
        model=result.model,
        prompt_version=result.prompt_version,
        trace_id=result.trace_id,
        audit_seq=result.audit_seq,
        phi_replaced=result.replaced,
    )
