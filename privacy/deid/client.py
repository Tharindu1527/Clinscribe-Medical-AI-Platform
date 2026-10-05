"""HTTP client for the de-ID service; along with the engine, the only source of DeidentifiedText."""

from dataclasses import dataclass

import httpx
from opentelemetry import propagate

from privacy.deid.types import DeidentifiedText, issue


@dataclass(frozen=True)
class DeidOutput:
    text: DeidentifiedText
    replaced: dict[str, int]  # entity type -> count, never the values


class DeidClient:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=60, transport=transport)

    def close(self) -> None:
        self._http.close()

    def deidentify(self, text: str, encounter_id: str) -> DeidOutput:
        headers: dict[str, str] = {}
        propagate.inject(headers)  # the de-ID span joins the caller's trace
        response = self._http.post(
            "/deidentify", json={"encounter_id": encounter_id, "text": text}, headers=headers
        )
        response.raise_for_status()
        body = response.json()
        replaced: dict[str, int] = {}
        for item in body["replacements"]:
            replaced[item["entity"]] = replaced.get(item["entity"], 0) + 1
        return DeidOutput(issue(body["text"], source="deid-service"), replaced)
