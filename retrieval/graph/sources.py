"""Graph sources: DDInter 2.0 interaction pairs and RxNorm names (ablation step 6).

- DDInter 2.0 (CC BY-NC-SA 4.0, data/LICENSES.md) publishes one CSV per ATC group. Its download page
  links 8 groups, but files for all 14 ATC groups are published at the same path; all 14 are used
  (without C and J, cardiovascular and anti-infective pairs such as clarithromycin-simvastatin would
  be missing). Rows: DDInterID_A, Drug_A, DDInterID_B, Drug_B, Level (Major/Moderate/Minor/Unknown).
- RxNorm via NLM RxNav (public data): each DDInter name is mapped to its ingredient (IN) RxCUI and
  brand names (BN), so "Eliquis" and "apixaban", or "lithium carbonate" and "lithium", meet in the
  graph. Responses are cached on D: so a rebuild needs no network.
"""

import csv
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
DDINTER_URL = "https://ddinter2.scbdd.com/static/media/download/ddinter_downloads_code_{group}.csv"
ATC_GROUPS = ("A", "B", "C", "D", "G", "H", "J", "L", "M", "N", "P", "R", "S", "V")
RXNAV = "https://rxnav.nlm.nih.gov/REST"
LEVELS = ("Major", "Moderate", "Minor", "Unknown")


@dataclass(frozen=True)
class Interaction:
    a: str  # DDInter id, a < b
    b: str
    level: str


@dataclass
class DrugRecord:
    ddinter_id: str
    name: str
    rxcui: str | None = None  # ingredient RxCUI, when RxNorm knows the name
    ingredient: str | None = None  # RxNorm ingredient name (e.g. "lithium" for lithium carbonate)
    brands: list[str] = field(default_factory=list)


def fetch_ddinter(client: httpx.Client, raw: Path = RAW / "ddinter") -> dict[str, str]:
    """Download the 14 CSVs once; returns file name -> SHA-256 (recorded in the graph manifest)."""
    raw.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for group in ATC_GROUPS:
        path = raw / f"code_{group}.csv"
        if not path.exists():
            response = client.get(DDINTER_URL.format(group=group))
            response.raise_for_status()
            path.write_bytes(response.content)
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def parse_ddinter(raw: Path = RAW / "ddinter") -> tuple[dict[str, str], list[Interaction]]:
    """Drug names by DDInter id, and unique undirected pairs (the same pair appears in several
    group files; levels never conflict in the 2024 release, and the most severe wins if they do)."""
    names: dict[str, str] = {}
    pairs: dict[tuple[str, str], str] = {}
    for group in ATC_GROUPS:
        with (raw / f"code_{group}.csv").open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                names[row["DDInterID_A"]] = row["Drug_A"].strip()
                names[row["DDInterID_B"]] = row["Drug_B"].strip()
                a, b = sorted((row["DDInterID_A"], row["DDInterID_B"]))
                level = row["Level"].strip() if row["Level"].strip() in LEVELS else "Unknown"
                current = pairs.get((a, b))
                if current is None or LEVELS.index(level) < LEVELS.index(current):
                    pairs[(a, b)] = level
    return names, [Interaction(a, b, level) for (a, b), level in sorted(pairs.items())]


class RxNav:
    """Tiny cached RxNav client (NLM asks for at most 20 requests per second)."""

    def __init__(self, client: httpx.Client, cache_path: Path = RAW / "rxnorm" / "rxnav.json"):
        self._client = client
        self._path = cache_path
        self._cache: dict[str, object] = (
            json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        )
        self._dirty = 0

    def get(self, path: str, params: dict[str, str]) -> object:
        key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if key not in self._cache:
            for attempt in range(3):
                try:
                    response = self._client.get(f"{RXNAV}/{path}", params=params)
                    if 400 <= response.status_code < 500:
                        response.raise_for_status()  # a bad request will not improve on retry
                    response.raise_for_status()
                    self._cache[key] = response.json()
                    break
                except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
                    # retry network errors, 5xx and empty/non-JSON bodies; not 4xx
                    status = getattr(getattr(exc, "response", None), "status_code", 500)
                    if attempt == 2 or 400 <= status < 500:
                        raise
                    time.sleep(2 * (attempt + 1))
            time.sleep(0.07)  # stay under 20 requests per second
            self._dirty += 1
            if self._dirty % 200 == 0:
                self.save()
        return self._cache[key]

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._cache, sort_keys=True), encoding="utf-8")


def _concepts(related: object) -> dict[str, list[tuple[str, str]]]:
    """tty -> [(rxcui, name)] from a related.json response."""
    out: dict[str, list[tuple[str, str]]] = {}
    groups = (related or {}).get("relatedGroup", {}).get("conceptGroup", []) or []  # type: ignore[attr-defined]
    for group in groups:
        for prop in group.get("conceptProperties", []) or []:
            out.setdefault(group["tty"], []).append((prop["rxcui"], prop["name"]))
    return out


def normalise(rxnav: RxNav, names: dict[str, str]) -> dict[str, DrugRecord]:
    """DDInter id -> record with ingredient RxCUI and brand names (when RxNorm has the name)."""
    records = {}
    for ddinter_id, name in sorted(names.items()):
        record = DrugRecord(ddinter_id, name)
        found = rxnav.get("rxcui.json", {"name": name, "search": "2"})
        ids = (found or {}).get("idGroup", {}).get("rxnormId") or []  # type: ignore[attr-defined]
        if ids:
            related = _concepts(rxnav.get(f"rxcui/{ids[0]}/related.json", {"tty": "IN BN"}))
            ingredients = related.get("IN") or []
            if len(ingredients) == 1:  # combination products (several INs) stay unmapped
                record.rxcui, record.ingredient = ingredients[0]
            elif not ingredients:
                record.rxcui = ids[0]  # the name is itself an ingredient
                record.ingredient = name.lower()
            record.brands = sorted({b for _, b in related.get("BN", [])})
        records[ddinter_id] = record
    rxnav.save()
    return records
