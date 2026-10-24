"""De-identification service (SPEC section 8). Sits before the gateway, logs and trace export.

POST /deidentify returns surrogate text and which entity types were replaced, never the originals.
Re-identification is a library function only; its HTTP route arrives with authentication (Phase 3).
Request and response bodies are never logged.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from config.db import app_conninfo
from config.settings import Settings
from llmops.telemetry.setup import configure_logging, configure_tracing, instrument
from privacy.deid.engine import Deidentifier, analyzer_for
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging()
    provider = configure_tracing(SERVICE, settings.otel_exporter_otlp_endpoint)
    store = PostgresStore(app_conninfo(settings), settings.deid_mapping_key)
    analyzer = analyzer_for(settings.deid_ner, settings.deid_spacy_model, settings.deid_tagger_path)
    app.state.deidentifier = Deidentifier(analyzer, store)
    yield
    provider.shutdown()


app = FastAPI(title="ClinScribe de-ID", version="0.1.0", lifespan=lifespan)
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
