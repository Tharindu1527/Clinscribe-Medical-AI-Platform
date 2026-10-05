"""ClinScribe API. Task 3 provides only the health endpoint; task 9 adds the pipeline endpoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import Settings
from llmops.telemetry.setup import configure_logging, configure_tracing, instrument

SERVICE = "api"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    provider = configure_tracing(SERVICE, Settings().otel_exporter_otlp_endpoint)
    yield
    provider.shutdown()


app = FastAPI(title="ClinScribe API", version="0.1.0", lifespan=lifespan)
instrument(app, SERVICE)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE}
