"""Build the Phase 2 corpus: fetch -> normalise -> de-duplicate -> chunk (PROGRESS task 1).

Usage: uv run python -m retrieval.ingest.pipeline [--offline] [--out DIR]
  --offline  use only the raw cache in data/corpus/raw (no network)
Writes DIR/docs.jsonl, DIR/chunks.jsonl and DIR/manifest.json (default DIR: data/corpus).
Output is deterministic for the same raw inputs: re-running gives byte-identical files.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import yaml

from retrieval.ingest.chunking import chunk_document
from retrieval.ingest.models import Chunk, Document, content_hash, garbled_share
from retrieval.ingest.sources import openfda, pmc, who

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "corpus.yaml"
DATA = ROOT / "data" / "corpus"
GARBLED_THRESHOLD = 0.02


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    config: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return config


def collect(config: dict[str, Any], raw: Path, offline: bool) -> list[Document]:
    transport = httpx.HTTPTransport(retries=3)
    headers = {"User-Agent": "clinscribe-ingest/0.1 (synthetic-data portfolio project)"}
    docs: list[Document] = []
    with httpx.Client(
        timeout=120, follow_redirects=True, headers=headers, transport=transport
    ) as c:
        for entry in config["who"]:
            if offline and not (raw / "who" / f"{entry['handle'].replace('/', '-')}.pdf").exists():
                continue
            docs.append(who.fetch(c, entry["handle"], entry["topic"], raw / "who"))
            print(f"who      {entry['handle']}: {len(docs[-1].sections)} sections")

        fda = config["openfda"]
        for generic in fda["drugs"]:
            if offline and not (raw / "openfda" / f"{openfda._slug(generic)}.json").exists():
                continue
            doc = openfda.fetch(c, generic, fda["sections"], "drug label", raw / "openfda")
            if doc is None:
                print(f"openfda  {generic}: no prescription label found")
                continue
            docs.append(doc)

        settings = config["pmc"]
        seen: set[str] = set()
        for query in settings["queries"]:
            query_dir = raw / "pmc" / query.replace(" ", "_")
            ids_file = (
                query_dir / "ids.json"
            )  # keeps relevance order, so reruns assign topics alike
            if offline:
                if not ids_file.exists():
                    continue
                ids = json.loads(ids_file.read_text(encoding="utf-8"))
            else:
                ids = pmc.search(c, query, settings["years"], settings["per_query"])
                query_dir.mkdir(parents=True, exist_ok=True)
                ids_file.write_text(json.dumps(ids), encoding="utf-8")
            articles = pmc.fetch_articles(c, ids, query_dir)
            kept = 0
            for number in ids:
                if number in seen or number not in articles:
                    continue
                doc = pmc.parse_article(articles[number], topic=query)
                if doc is not None:
                    seen.add(number)
                    docs.append(doc)
                    kept += 1
            print(f"pmc      {query!r}: {len(ids)} found, {kept} kept (CC BY/CC0 with full text)")
    return docs


def dedupe_documents(docs: list[Document]) -> list[Document]:
    unique: dict[str, Document] = {}
    hashes: set[str] = set()
    for doc in sorted(docs, key=lambda d: d.id):
        digest = content_hash(" ".join(s.text for s in doc.sections))
        if doc.id in unique or digest in hashes or not doc.sections:
            continue
        unique[doc.id] = doc
        hashes.add(digest)
    return list(unique.values())


def dedupe_chunks(chunks: list[Chunk]) -> list[Chunk]:
    seen: set[str] = set()
    kept = []
    for chunk in chunks:
        digest = content_hash(chunk.text)
        if digest not in seen:
            seen.add(digest)
            kept.append(chunk)
    return kept


def write_jsonl(path: Path, rows: list[Any]) -> str:
    text = "".join(
        json.dumps(r.model_dump(), ensure_ascii=False, sort_keys=True) + "\n" for r in rows
    )
    path.write_text(text, encoding="utf-8", newline="\n")
    return hashlib.sha256(text.encode()).hexdigest()


def build(config: dict[str, Any], out: Path, raw: Path, offline: bool) -> dict[str, Any]:
    docs = dedupe_documents(collect(config, raw, offline))
    c = config["chunking"]
    chunks = dedupe_chunks(
        [
            ch
            for d in docs
            for ch in chunk_document(d, c["target_words"], c["overlap_words"], c["min_words"])
        ]
    )
    out.mkdir(parents=True, exist_ok=True)
    words = sorted(len(ch.text.split()) for ch in chunks)
    manifest = {
        "documents": len(docs),
        "chunks": len(chunks),
        "documents_by_source": dict(sorted(Counter(d.source for d in docs).items())),
        "chunks_by_source": dict(sorted(Counter(ch.source for ch in chunks).items())),
        "licences": dict(sorted(Counter(d.license for d in docs).items())),
        "chunk_words": {"min": words[0], "median": words[len(words) // 2], "max": words[-1]}
        if words
        else {},
        # chunks where > 2% of characters are outside normal clinical English (broken PDF fonts)
        "garbled_chunks": sum(1 for ch in chunks if garbled_share(ch.text) > GARBLED_THRESHOLD),
        "docs_sha256": write_jsonl(out / "docs.jsonl", docs),
        "chunks_sha256": write_jsonl(out / "chunks.jsonl", chunks),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--out", type=Path, default=DATA)
    args = parser.parse_args(argv)
    manifest = build(load_config(), args.out, DATA / "raw", args.offline)
    print(json.dumps({k: v for k, v in manifest.items() if not k.endswith("sha256")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
