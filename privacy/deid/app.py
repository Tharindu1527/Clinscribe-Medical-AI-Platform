"""De-identification service. Task 3 provides only the health endpoint; task 6 adds /deidentify."""

from fastapi import FastAPI

app = FastAPI(title="ClinScribe de-ID", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "deid"}
