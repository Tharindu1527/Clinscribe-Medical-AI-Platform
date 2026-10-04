"""ClinScribe API. Task 3 provides only the health endpoint; task 9 adds the pipeline endpoint."""

from fastapi import FastAPI

app = FastAPI(title="ClinScribe API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api"}
