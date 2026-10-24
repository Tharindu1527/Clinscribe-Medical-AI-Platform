"""De-identification service (SPEC section 8). Sits before the gateway, logs and trace export.

POST /deidentify returns surrogate text and which entity types were replaced, never the originals.
POST /reidentify restores originals for the doctor's own screen (ADR-0015). Only the API may call
it: it needs the X-Reidentify-Key header (DEID_REIDENTIFY_KEY, held by the API and this service
only); the API checks the doctor's role and audits every call. Request and response bodies are
never logged.
"""

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from config.db import app_conninfo
from config.settings import Settings
from llmops.telemetry.setup import (
    FASTAPI_TELEMETRY,
    configure_logging,
    configure_tracing,
    instrument,
)
from privacy.deid.engine import SURROGATE_RE, Deidentifier, analyzer_for
from privacy.deid.store import PostgresStore

SERVICE = "deid"


class DeidRequest(BaseModel):
    encounter_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    text: str = Field(max_length=100_000)


class ReplacementOut(BaseModel):
    entity: str
    surrogate: str


class DeidResponse(BaseModel):
    text: str
    replacements: list[ReplacementOut]


class ReidRequest(BaseModel):
    encounter_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    texts: list[str] = Field(max_length=1000)


class ReidResponse(BaseModel):
    texts: list[str]
    restored: int  # surrogates replaced by their originals (unknown surrogates stay as they are)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging()
    provider = configure_tracing(SERVICE, settings.otel_exporter_otlp_endpoint)
    store = PostgresStore(app_conninfo(settings), settings.deid_mapping_key)
    analyzer = analyzer_for(settings.deid_ner, settings.deid_spacy_model, settings.deid_tagger_path)
    app.state.deidentifier = Deidentifier(analyzer, store)
    app.state.reidentify_key = settings.deid_reidentify_key.get_secret_value()
    yield
    provider.shutdown()


app = FastAPI(
    title="ClinScribe de-ID", version="0.1.0", lifespan=lifespan, telemetry=FASTAPI_TELEMETRY
)
instrument(app, SERVICE)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE}


@app.post("/deidentify")
def deidentify(request: DeidRequest) -> DeidResponse:
    deidentifier: Deidentifier = app.state.deidentifier
    result = deidentifier.deidentify(request.text, request.encounter_id)
    return DeidResponse(
        text=result.text.text,
        replacements=[
            ReplacementOut(entity=r.entity, surrogate=r.surrogate) for r in result.replacements
        ],
    )


@app.post("/reidentify")
def reidentify(
    request: ReidRequest, x_reidentify_key: Annotated[str, Header()] = ""
) -> ReidResponse:
    expected: str = app.state.reidentify_key
    if not expected or not hmac.compare_digest(x_reidentify_key.encode(), expected.encode()):
        raise HTTPException(403, "re-identification is only for the API")
    deidentifier: Deidentifier = app.state.deidentifier
    texts = [deidentifier.reidentify(text, request.encounter_id) for text in request.texts]
    before = sum(len(SURROGATE_RE.findall(text)) for text in request.texts)
    after = sum(len(SURROGATE_RE.findall(text)) for text in texts)
    return ReidResponse(texts=texts, restored=before - after)
