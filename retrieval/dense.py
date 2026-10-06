"""Dense retrieval: embed corpus chunks with a local encoder and search them in Qdrant.

Ablation step 1 (dense-only baseline). The encoder runs in-process on CPU (ADR-0001: local
encoders see only public corpus text and de-identified queries). Embeddings are cached in
data/index/, keyed by the corpus hash and the pinned model revision, so recreating the Qdrant
collection does not mean re-embedding 8k chunks.

Usage: uv run python -m retrieval.dense [--recreate] [--device cpu|cuda]
"""

import argparse
import hashlib
import json
import sys
import time
import uuid
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import yaml
from numpy.typing import NDArray
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from config.settings import Settings
from privacy.deid.types import DeidentifiedText

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "corpus"
INDEX_DIR = ROOT / "data" / "index"
POINT_NAMESPACE = uuid.UUID("6f1c2a7e-3b0d-4c55-9a51-2f6c1d0e8b44")  # fixed: ids stay stable
PAYLOAD_KEYS = ("id", "doc_id", "source", "title", "section", "url", "license", "topic", "text")
UPSERT_BATCH = 256
SHARD_SIZE = 512  # chunks per saved embedding shard (resume point)


class DenseConfig(BaseModel):
    model: str
    revision: str
    query_prefix: str
    document_prefix: str
    max_seq_length: int
    batch_size: int
    collection: str


class Hit(BaseModel):
    chunk_id: str
    score: float


class Encoder(Protocol):
    dim: int

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        """Unit-length vectors, one row per text."""
        ...


def load_config(path: Path = ROOT / "config" / "retrieval.yaml") -> DenseConfig:
    return DenseConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))["dense"])


def point_id(chunk_id: str) -> str:
    """Qdrant needs integer or UUID ids; a UUIDv5 of the chunk id is stable across rebuilds."""
    return str(uuid.uuid5(POINT_NAMESPACE, chunk_id))


def fingerprint(cfg: DenseConfig, chunks_sha256: str) -> str:
    """Changes whenever the corpus or anything that affects a document vector changes."""
    parts = [chunks_sha256, cfg.model, cfg.revision, cfg.document_prefix, str(cfg.max_seq_length)]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


class SentenceTransformerEncoder:
    """Loads the pinned model revision into HF_HOME (on D:); never runs remote code."""

    def __init__(self, cfg: DenseConfig, prefix: str, device: str = "cpu") -> None:
        from sentence_transformers import SentenceTransformer  # heavy import (torch): lazy

        self._model = SentenceTransformer(
            cfg.model, revision=cfg.revision, device=device, trust_remote_code=False
        )
        self._model.max_seq_length = cfg.max_seq_length
        self._prefix = prefix
        self._batch_size = cfg.batch_size
        self.dim = int(self._model.get_embedding_dimension() or 0)

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        vectors = self._model.encode(
            [self._prefix + text for text in texts],
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > 100,
        )
        return np.asarray(vectors, dtype=np.float32)


def connect(settings: Settings | None = None) -> QdrantClient:
    settings = settings or Settings()
    with warnings.catch_warnings():
        # Plain HTTP is fine here: Qdrant listens on 127.0.0.1 / the Compose network only
        warnings.filterwarnings("ignore", message="Api key is used with an insecure connection")
        return QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key.get_secret_value() or None,
            timeout=60,
        )


def load_chunks(corpus: Path = CORPUS) -> tuple[list[dict[str, str]], str]:
    """Corpus chunks in file order, and the corpus hash from the manifest."""
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    lines = (corpus / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines], str(manifest["chunks_sha256"])


def document_vectors(
    cfg: DenseConfig,
    chunks: Sequence[dict[str, str]],
    chunks_sha256: str,
    encoder_factory: Any,
    index_dir: Path = INDEX_DIR,
) -> tuple[NDArray[np.float32], dict[str, Any]]:
    """Cached vectors if the fingerprint matches, else embed and cache. Returns (vectors, meta).

    Vectors are saved per shard of SHARD_SIZE chunks, so an interrupted run (CPU encoding takes tens
    of minutes) resumes from the last finished shard instead of starting again.
    """
    expected = fingerprint(cfg, chunks_sha256)
    shard_dir = index_dir / f"{cfg.collection}-{expected[:12]}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    meta_path = shard_dir / "meta.json"
    if meta_path.exists():
        meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("fingerprint") == expected and meta.get("count") == len(chunks):
            return np.load(shard_dir / "vectors.npy"), {**meta, "cached": True}

    encoder: Encoder | None = None
    shards: list[NDArray[np.float32]] = []
    embedded, seconds = 0, 0.0
    starts = range(0, len(chunks), SHARD_SIZE)
    for number, start in enumerate(starts):
        path = shard_dir / f"{number:05d}.npy"
        if path.exists():
            shards.append(np.load(path))
            continue
        encoder = encoder or encoder_factory(cfg, cfg.document_prefix)
        batch = chunks[start : start + SHARD_SIZE]
        started = time.perf_counter()
        shard = encoder.encode([chunk["text"] for chunk in batch])
        seconds += time.perf_counter() - started
        embedded += len(batch)
        np.save(path, shard)
        shards.append(shard)
        rate = embedded / seconds if seconds else 0.0
        print(
            f"shard {number + 1}/{len(starts)}: {rate:.1f} chunks/s, "
            f"~{(len(chunks) - start - len(batch)) / rate / 60 if rate else 0:.0f} min left",
            file=sys.stderr,
            flush=True,
        )
    vectors = np.concatenate(shards)
    meta = {
        "fingerprint": expected,
        "model": cfg.model,
        "revision": cfg.revision,
        "count": len(chunks),
        "dim": int(vectors.shape[1]),
        "embedded_now": embedded,
        "embed_seconds": round(seconds, 1),
        "chunks_per_second": round(embedded / seconds, 2) if seconds else None,
    }
    np.save(shard_dir / "vectors.npy", vectors)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return vectors, {**meta, "cached": False}


def build_index(
    cfg: DenseConfig,
    client: QdrantClient,
    chunks: Sequence[dict[str, str]],
    chunks_sha256: str,
    encoder_factory: Any,
    index_dir: Path = INDEX_DIR,
    recreate: bool = False,
) -> dict[str, Any]:
    """Make the collection hold exactly one point per chunk; skip work that is already done."""
    vectors, meta = document_vectors(cfg, chunks, chunks_sha256, encoder_factory, index_dir)
    exists = client.collection_exists(cfg.collection)
    if exists and not recreate:
        info = client.get_collection(cfg.collection)
        stored = (info.config.metadata or {}).get("fingerprint")
        if stored == meta["fingerprint"] and info.points_count == len(chunks):
            return {**meta, "upserted": 0}
    if exists:
        client.delete_collection(cfg.collection)
    client.create_collection(
        cfg.collection,
        vectors_config=VectorParams(size=int(vectors.shape[1]), distance=Distance.COSINE),
        metadata={"fingerprint": meta["fingerprint"], "model": cfg.model},
    )
    started = time.perf_counter()
    for start in range(0, len(chunks), UPSERT_BATCH):
        batch = chunks[start : start + UPSERT_BATCH]
        client.upsert(
            cfg.collection,
            points=[
                PointStruct(
                    id=point_id(chunk["id"]),
                    vector=vectors[start + i].tolist(),
                    payload={key: chunk[key] for key in PAYLOAD_KEYS},
                )
                for i, chunk in enumerate(batch)
            ],
            wait=True,
        )
    return {**meta, "upserted": len(chunks), "upsert_seconds": round(time.perf_counter() - started)}


class DenseRetriever:
    def __init__(self, cfg: DenseConfig, client: QdrantClient, encoder: Encoder) -> None:
        self._cfg = cfg
        self._client = client
        self._encoder = encoder

    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]:
        """Top-k chunks by cosine similarity. Only de-identified text may reach the encoder."""
        if not isinstance(query, DeidentifiedText):
            raise TypeError("DenseRetriever.search accepts only DeidentifiedText")
        vector = self._encoder.encode([query.text])[0]
        result = self._client.query_points(
            self._cfg.collection, query=vector.tolist(), limit=k, with_payload=["id"]
        )
        return [Hit(chunk_id=str((p.payload or {})["id"]), score=p.score) for p in result.points]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recreate", action="store_true", help="drop and reload the collection")
    parser.add_argument("--device", default="cpu", help="cpu (default) or cuda")
    args = parser.parse_args(argv)

    cfg = load_config()
    chunks, chunks_sha256 = load_chunks()

    def factory(config: DenseConfig, prefix: str) -> Encoder:
        return SentenceTransformerEncoder(config, prefix, device=args.device)

    report = build_index(cfg, connect(), chunks, chunks_sha256, factory, recreate=args.recreate)
    print(json.dumps({k: v for k, v in report.items() if k != "fingerprint"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
