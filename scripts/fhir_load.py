"""Generate Synthea patients and load them into HAPI FHIR (PROGRESS task 4).

Usage: uv run python -m scripts.fhir_load
Steps:
  1. download the pinned Synthea jar into data/synthea/ and verify its SHA-256;
  2. generate patients with a fixed seed (docker compose `synthea` service, profile `tools`),
     unless output already exists;
  3. load FHIR bundles in dependency order: organisations, practitioners, then patients.
Loading is idempotent: a patient whose Synthea identifier is already on the server is skipped,
and organisation/practitioner bundles use conditional creates.
All data is synthetic (SPEC section 9). Licence: Apache-2.0, recorded in data/LICENSES.md.
"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from config.settings import Settings

SYNTHEA_VERSION = "v4.0.0"
JAR_URL = (
    "https://github.com/synthetichealth/synthea/releases/download/"
    f"{SYNTHEA_VERSION}/synthea-with-dependencies.jar"
)
JAR_SHA256 = "ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1"
SYNTHEA_DIR = Path("data/synthea")
JAR_PATH = SYNTHEA_DIR / "synthea-with-dependencies.jar"
FHIR_OUT = SYNTHEA_DIR / "output" / "fhir"
SYNTHEA_ID_SYSTEM = "https://github.com/synthetichealth/synthea"
FHIR_JSON = "application/fhir+json"
# HAPI reuses search results for ~60 s; without this, a "not found" from just before a load is
# served again and the patient is posted twice (seen in CI, where the reload test runs right after).
NO_CACHE = {"Cache-Control": "no-cache"}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_jar(attempts: int = 20) -> None:
    """Download the jar (resuming on flaky networks) and verify its checksum."""
    SYNTHEA_DIR.mkdir(parents=True, exist_ok=True)
    if JAR_PATH.exists() and sha256_of(JAR_PATH) == JAR_SHA256:
        return
    for attempt in range(1, attempts + 1):
        start = JAR_PATH.stat().st_size if JAR_PATH.exists() else 0
        headers = {"Range": f"bytes={start}-"} if start else {}
        try:
            with (
                httpx.stream(
                    "GET", JAR_URL, headers=headers, follow_redirects=True, timeout=60
                ) as r,
                JAR_PATH.open("ab" if r.status_code == 206 else "wb") as out,
            ):
                r.raise_for_status()
                for chunk in r.iter_bytes(1 << 20):
                    out.write(chunk)
            break
        except httpx.HTTPError as exc:
            print(f"download attempt {attempt} failed: {exc}")
            time.sleep(5)
    actual = sha256_of(JAR_PATH)
    if actual != JAR_SHA256:
        JAR_PATH.unlink()
        raise SystemExit(f"Synthea jar checksum mismatch ({actual}); deleted, run again")


def generate() -> None:
    if FHIR_OUT.exists() and any(FHIR_OUT.glob("*.json")):
        print(f"Synthea output already present in {FHIR_OUT}; skipping generation")
        return
    subprocess.run(
        ["docker", "compose", "--profile", "tools", "run", "--rm", "synthea"], check=True
    )


def bundle_order(paths: list[Path]) -> list[Path]:
    """Organisations first, then practitioners, then patients (patients reference both)."""

    def rank(path: Path) -> tuple[int, str]:
        name = path.name
        if name.startswith("hospitalInformation"):
            return (0, name)
        if name.startswith("practitionerInformation"):
            return (1, name)
        return (2, name)

    return sorted(paths, key=rank)


def synthea_patient_id(bundle: dict[str, Any]) -> str | None:
    """The Synthea identifier of the bundle's Patient, or None for non-patient bundles."""
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Patient":
            for identifier in resource.get("identifier", []):
                if identifier.get("system") == SYNTHEA_ID_SYSTEM:
                    return str(identifier["value"])
    return None


def load(client: httpx.Client) -> dict[str, int]:
    counts = {"loaded": 0, "skipped": 0}
    for path in bundle_order(list(FHIR_OUT.glob("*.json"))):
        bundle = json.loads(path.read_text(encoding="utf-8"))
        patient_id = synthea_patient_id(bundle)
        if patient_id:
            found = client.get(
                "Patient",
                params={"identifier": f"{SYNTHEA_ID_SYSTEM}|{patient_id}", "_summary": "count"},
                headers=NO_CACHE,
            )
            found.raise_for_status()
            if found.json().get("total", 0) > 0:
                counts["skipped"] += 1
                continue
        response = client.post("", json=bundle, headers={"Content-Type": FHIR_JSON})
        if response.status_code >= 400:
            raise SystemExit(f"{path.name}: HTTP {response.status_code} {response.text[:300]}")
        counts["loaded"] += 1
    return counts


def main() -> int:
    settings = Settings()
    ensure_jar()
    generate()
    with httpx.Client(base_url=settings.fhir_base_url.rstrip("/") + "/", timeout=300) as client:
        counts = load(client)
        total = (
            client.get("Patient", params={"_summary": "count"}, headers=NO_CACHE)
            .json()
            .get("total")
        )
    print(f"bundles loaded: {counts['loaded']}, skipped (already present): {counts['skipped']}")
    print(f"patients on the FHIR server: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
