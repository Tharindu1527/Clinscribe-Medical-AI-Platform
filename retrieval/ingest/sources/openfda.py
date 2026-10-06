"""openFDA drug labels (SPL): the most recent prescription label per generic name. CC0."""

import json
from pathlib import Path
from typing import Any

import httpx

from retrieval.ingest.models import Document, Section, normalise_text

LABEL_API = "https://api.fda.gov/drug/label.json"


def _slug(name: str) -> str:
    return "-".join(name.lower().split())


def parse_label(label: dict[str, Any], generic: str, sections: list[str], topic: str) -> Document:
    openfda = label.get("openfda", {})
    brand = (openfda.get("brand_name") or [generic])[0]
    set_id = label["set_id"]
    found = []
    for key in sections:
        values = label.get(key)
        if not values:
            continue
        text = normalise_text(" ".join(values))
        if text:
            found.append(Section(title=key.replace("_", " ").capitalize(), text=text))
    return Document(
        id=f"fda:{set_id}",
        source="openfda",
        title=f"{brand} ({generic}) prescribing information",
        url=f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={set_id}",
        license="CC0 1.0 (openFDA)",
        topic=topic,
        published=label.get("effective_time"),
        sections=found,
    )


def matches_generic(label: dict[str, Any], generic: str) -> bool:
    """True if the label is the requested product itself, not a combination containing it.

    "amlodipine" must not pick "Amlodipine Besylate and Benazepril"; a requested combination
    ("amoxicillin and clavulanate potassium") must match all of its ingredients. Salts are allowed:
    "AMLODIPINE BESYLATE" matches "amlodipine".
    """
    wanted = [part.split()[0] for part in generic.lower().split(" and ")]
    for name in label.get("openfda", {}).get("generic_name", []):
        parts = [part.strip() for part in name.lower().split(" and ")]
        if len(parts) == len(wanted) and all(any(p.startswith(w) for p in parts) for w in wanted):
            return True
    return False


def fetch(
    client: httpx.Client, generic: str, sections: list[str], topic: str, raw_dir: Path
) -> Document | None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache = raw_dir / f"{_slug(generic)}.json"
    if cache.exists():
        label = json.loads(cache.read_text(encoding="utf-8"))
    else:
        search = (
            f'openfda.generic_name:"{generic}" AND openfda.product_type:"HUMAN PRESCRIPTION DRUG"'
        )
        response = client.get(
            LABEL_API, params={"search": search, "sort": "effective_time:desc", "limit": 50}
        )
        if response.status_code == 404:  # openFDA answers 404 when nothing matches
            return None
        response.raise_for_status()
        # newest label that is exactly this product (the search also returns combinations)
        exact = [r for r in response.json()["results"] if matches_generic(r, generic)]
        if not exact:
            return None
        label = exact[0]
        cache.write_text(json.dumps(label), encoding="utf-8")
    return parse_label(label, generic, sections, topic)
