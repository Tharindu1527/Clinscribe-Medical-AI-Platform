"""HTTP client for the de-ID service; along with the engine, the only source of DeidentifiedText.

`reidentify` works only for a client given the re-identification key (the API, ADR-0015); its
output holds PHI and must go nowhere but the doctor's screen and the approved record."""

from dataclasses import dataclass

import httpx
from opentelemetry import propagate

from privacy.deid.types import DeidentifiedText, issue


@dataclass(frozen=True)
class DeidOutput:
    text: DeidentifiedText
    replaced: dict[str, int]  # entity type -> count, never the values


@dataclass(frozen=True)
class Reidentified:
    texts: list[str]  # PHI: for the doctor's screen and the approved record only
    restored: int


class DeidClient:
    def __init__(
        self,
        base_url: str,
        transport: httpx.BaseTransport | None = None,
        reidentify_key: str = "",
    ) -> None:
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=60, transport=transport)
        self._reidentify_key = reidentify_key

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

    def reidentify(self, texts: list[str], encounter_id: str) -> Reidentified:
        if not self._reidentify_key:
            raise RuntimeError("this client has no re-identification key (only the API does)")
        headers = {"X-Reidentify-Key": self._reidentify_key}
        propagate.inject(headers)
        response = self._http.post(
            "/reidentify", json={"encounter_id": encounter_id, "texts": texts}, headers=headers
        )
        response.raise_for_status()
        body = response.json()
        return Reidentified(texts=body["texts"], restored=body["restored"])
