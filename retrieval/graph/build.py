"""Build the drug-interaction graph in Neo4j (Phase 2 task 9, ablation step 6).

  uv run python -m retrieval.graph.build --sources-only   download DDInter, map names with RxNav
  uv run python -m retrieval.graph.build                  ... then load Neo4j and print counts

Graph:  (:Drug {key, name, rxcui, ingredient, brands})-[:INTERACTS_WITH {level, source}]-(:Drug)
        (:Chunk {id, doc_id, section, interaction_section})-[:MENTIONS]->(:Drug)
Drug keys are DDInter ids. MENTIONS edges come from the drug lexicon (retrieval/graph/lexicon.py)
matched over the raw corpus chunks. Records are cached in data/graph/ (git-ignored, on D:).
"""

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from retrieval.graph.sources import RAW, RxNav, fetch_ddinter, normalise, parse_ddinter

ROOT = Path(__file__).resolve().parents[2]
GRAPH_DIR = ROOT / "data" / "graph"


def build_sources(out: Path = GRAPH_DIR) -> dict[str, Any]:
    """Download DDInter, map every drug through RxNav, write drugs.jsonl + interactions.jsonl."""
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60) as client:
        hashes = fetch_ddinter(client)
        names, interactions = parse_ddinter()
        started = time.perf_counter()
        records = normalise(RxNav(client), names)
    drugs = [asdict(r) for r in records.values()]
    (out / "drugs.jsonl").write_text(
        "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in drugs), encoding="utf-8"
    )
    data = "".join(json.dumps(asdict(i)) + "\n" for i in interactions).encode("utf-8")
    (out / "interactions.jsonl").write_bytes(data)
    manifest = {
        "ddinter_files": hashes,
        "drugs": len(drugs),
        "drugs_with_rxcui": sum(1 for d in drugs if d["rxcui"]),
        "drugs_with_brands": sum(1 for d in drugs if d["brands"]),
        "interactions": len(interactions),
        "interactions_sha256": hashlib.sha256(data).hexdigest(),
        "rxnav_seconds": round(time.perf_counter() - started, 1),
        "rxnav_cache": str((RAW / "rxnorm" / "rxnav.json").relative_to(ROOT)),
    }
    (out / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the drug-interaction graph")
    parser.add_argument("--sources-only", action="store_true")
    args = parser.parse_args(argv)
    manifest = build_sources()
    print(json.dumps({k: v for k, v in manifest.items() if k != "ddinter_files"}, indent=2))
    if args.sources_only:
        return 0
    from retrieval.graph.load import load_graph  # needs the rag profile (Neo4j)

    print(json.dumps(load_graph(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
