"""Late chunking (ablation step 5, Günther et al. 2024): embed a whole section once, then mean-pool
each chunk's own token vectors, so every chunk vector "sees" the rest of its section.

Same model as the dense baseline (ModernBERT Embed, ADR-0005: mean pooling + L2 norm), same chunks,
same queries; only the document vectors change, so the comparison isolates the method. Compared
with contextual retrieval, not stacked on it (Phase 2 plan).

- A section is encoded as [CLS] "search_document: " section-tokens [SEP]. Sections longer than
  `max_tokens` (44 of 3,211) are split into overlapping windows; a chunk is pooled from the window
  in which it sits most centrally. A chunk longer than the overlap (10 table chunks reach 1,753
  tokens) may fit no standard window: it gets its own window centred on it.
- A chunk's tokens are those whose character offsets fall inside the chunk's span in the section
  text (every chunk is a verbatim substring of its section, checked at build time).
- max_tokens is 4,096, not the model's 8,192: a full 8k global-attention layer needs ~3 GB on CPU.

Vectors are cached per shard of sections (resumable), then loaded into Qdrant as
`<dense collection>_late`.

Usage: uv run python -m retrieval.late_chunking
"""

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from numpy.typing import NDArray
from pydantic import BaseModel

from retrieval.dense import CORPUS, INDEX_DIR, ROOT, DenseConfig

SHARD_SECTIONS = 200  # sections per cached shard (resume point)


class LateConfig(BaseModel):
    max_tokens: int  # tokens per encoded window, special tokens and prefix included
    overlap_tokens: int  # overlap between windows of a long section
    batch_tokens: int  # padded tokens per forward pass (memory bound on CPU)
    collection_suffix: str


def load_config(path: Path = ROOT / "config" / "retrieval.yaml") -> LateConfig:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    return LateConfig.model_validate(cfg["late_chunking"])


def windows(n_tokens: int, size: int, overlap: int) -> list[tuple[int, int]]:
    """Token windows [start, end) covering n_tokens: each at most `size`, overlapping `overlap`."""
    if n_tokens <= size:
        return [(0, n_tokens)]
    step = size - overlap
    if step <= 0:
        raise ValueError("overlap must be smaller than the window size")
    out = []
    start = 0
    while True:
        end = min(start + size, n_tokens)
        out.append((start, end))
        if end == n_tokens:
            return out
        start += step


def chunk_token_spans(
    offsets: Sequence[tuple[int, int]], char_spans: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Token index range [first, last + 1) of each character span (tokens overlapping the span)."""
    spans = []
    for start, end in char_spans:
        inside = [i for i, (a, b) in enumerate(offsets) if b > start and a < end]
        if not inside:
            raise ValueError(f"no tokens inside characters {start}-{end}")
        spans.append((inside[0], inside[-1] + 1))
    return spans


def best_window(span: tuple[int, int], wins: Sequence[tuple[int, int]]) -> int:
    """Index of the window that fully contains the span with the most room on both sides."""
    first, last = span
    containing = [i for i, (s, e) in enumerate(wins) if s <= first and last <= e]
    if not containing:
        raise ValueError(f"no window contains tokens {first}-{last}; raise overlap_tokens")
    return max(containing, key=lambda i: min(first - wins[i][0], wins[i][1] - last))


def assign_windows(
    spans: Sequence[tuple[int, int]], wins: Sequence[tuple[int, int]], size: int, n_tokens: int
) -> tuple[list[tuple[int, int]], list[int]]:
    """Window index for each chunk span; adds a window centred on any chunk no window contains."""
    out = list(wins)
    assignment = []
    for first, last in spans:
        try:
            assignment.append(best_window((first, last), out))
        except ValueError:
            if last - first > size:
                raise ValueError(
                    f"chunk of {last - first} tokens exceeds the window size"
                ) from None
            start = max(0, min((first + last - size) // 2, n_tokens - size))
            out.append((start, min(start + size, n_tokens)))
            assignment.append(len(out) - 1)
    return out, assignment


def section_chunks(
    chunks: Sequence[dict[str, str]],
) -> dict[tuple[str, int], list[dict[str, str]]]:
    """Chunks grouped by (doc id, section index), in corpus order."""
    grouped: dict[tuple[str, int], list[dict[str, str]]] = {}
    for chunk in chunks:
        section = int(chunk["id"].split("#")[1].removeprefix("s"))
        grouped.setdefault((chunk["doc_id"], section), []).append(chunk)
    return grouped


def char_spans(section_text: str, chunks: Sequence[dict[str, str]]) -> list[tuple[int, int]]:
    """Character span of each chunk in its section; chunks are in order and may overlap."""
    spans = []
    cursor = 0
    for chunk in chunks:
        start = section_text.find(chunk["text"], cursor)
        if start < 0:
            start = section_text.find(chunk["text"])  # defensive: out-of-order overlap
        if start < 0:
            raise ValueError(f"{chunk['id']} is not a substring of its section")
        spans.append((start, start + len(chunk["text"])))
        cursor = start + 1
    return spans


class LateChunkingEncoder:
    def __init__(self, dense: DenseConfig, late: LateConfig, device: str = "cpu") -> None:
        import torch  # heavy: lazy
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self._device = device
        self.tokenizer = AutoTokenizer.from_pretrained(dense.model, revision=dense.revision)
        model: Any = AutoModel.from_pretrained(
            dense.model, revision=dense.revision
        )  # loose HF typing
        model.to(torch.device(device))
        self.model = model.eval()
        self.late = late
        self.prefix_ids: list[int] = self.tokenizer(
            dense.document_prefix.rstrip(), add_special_tokens=False
        )["input_ids"]
        self.cls_id = int(self.tokenizer.cls_token_id)
        self.sep_id = int(self.tokenizer.sep_token_id)
        self.pad_id = int(self.tokenizer.pad_token_id)

    @property
    def content_size(self) -> int:
        return self.late.max_tokens - 2 - len(self.prefix_ids)

    def _forward(self, sequences: list[list[int]]) -> list[NDArray[np.float32]]:
        """Token vectors for each sequence, batched under the padded-token budget."""
        torch = self._torch
        order = sorted(range(len(sequences)), key=lambda i: len(sequences[i]))
        out: list[NDArray[np.float32] | None] = [None] * len(sequences)
        batch: list[int] = []

        def run(batch: list[int]) -> None:
            width = max(len(sequences[i]) for i in batch)
            ids = torch.full((len(batch), width), self.pad_id, dtype=torch.long)
            mask = torch.zeros((len(batch), width), dtype=torch.long)
            for row, i in enumerate(batch):
                ids[row, : len(sequences[i])] = torch.tensor(sequences[i])
                mask[row, : len(sequences[i])] = 1
            with torch.inference_mode():
                hidden = self.model(
                    input_ids=ids.to(self._device), attention_mask=mask.to(self._device)
                )
            states = hidden.last_hidden_state.float().cpu().numpy()
            for row, i in enumerate(batch):
                out[i] = states[row, : len(sequences[i])]

        for i in order:
            width = max([len(sequences[j]) for j in batch] + [len(sequences[i])])
            if batch and width * (len(batch) + 1) > self.late.batch_tokens:
                run(batch)
                batch = []
            batch.append(i)
        if batch:
            run(batch)
        return [o for o in out if o is not None]

    def encode_sections(
        self, sections: Sequence[tuple[str, Sequence[dict[str, str]]]]
    ) -> list[NDArray[np.float32]]:
        """For each (section text, its chunks): one unit vector per chunk, in chunk order."""
        jobs: list[tuple[int, int, list[tuple[int, int]]]] = []  # (section, window, chunk spans)
        sequences: list[list[int]] = []
        layouts = []
        for s_idx, (text, chunks) in enumerate(sections):
            # a leading space, as after "search_document:" in the baseline (BPE marks word starts)
            enc = self.tokenizer(" " + text, add_special_tokens=False, return_offsets_mapping=True)
            ids = enc["input_ids"]
            offsets = [(max(a - 1, 0), max(b - 1, 0)) for a, b in enc["offset_mapping"]]
            spans = chunk_token_spans(offsets, char_spans(text, chunks))
            wins, assignment = assign_windows(
                spans,
                windows(len(ids), self.content_size, self.late.overlap_tokens),
                self.content_size,
                len(ids),
            )
            layouts.append((spans, wins, assignment))
            for w_idx, (start, end) in enumerate(wins):
                if w_idx in assignment:
                    sequences.append([self.cls_id, *self.prefix_ids, *ids[start:end], self.sep_id])
                    jobs.append((s_idx, w_idx, []))
        states = self._forward(sequences)
        by_window = {(s, w): states[n] for n, (s, w, _) in enumerate(jobs)}
        lead = 1 + len(self.prefix_ids)  # [CLS] + prefix tokens before the content
        results = []
        for s_idx, (spans, wins, assignment) in enumerate(layouts):
            rows = []
            for (first, last), w_idx in zip(spans, assignment, strict=True):
                start = wins[w_idx][0]
                tokens = by_window[(s_idx, w_idx)][lead + first - start : lead + last - start]
                vector = tokens.mean(axis=0)
                rows.append(vector / max(float(np.linalg.norm(vector)), 1e-12))
            results.append(np.asarray(rows, dtype=np.float32))
        return results


def late_fingerprint(dense: DenseConfig, late: LateConfig, chunks_sha256: str) -> str:
    parts = [
        chunks_sha256,
        dense.model,
        dense.revision,
        dense.document_prefix,
        "late",
        str(late.max_tokens),
        str(late.overlap_tokens),
    ]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def build_vectors(
    dense: DenseConfig,
    late: LateConfig,
    docs: Sequence[dict[str, Any]],
    chunks: Sequence[dict[str, str]],
    chunks_sha256: str,
    encoder_factory: Any,
    index_dir: Path = INDEX_DIR,
) -> tuple[NDArray[np.float32], dict[str, Any]]:
    """One late-chunked vector per chunk (corpus order), cached per shard of sections."""
    fp = late_fingerprint(dense, late, chunks_sha256)
    folder = index_dir / f"{dense.collection}{late.collection_suffix}-{fp[:12]}"
    folder.mkdir(parents=True, exist_ok=True)
    meta_path = folder / "meta.json"
    if meta_path.exists():
        return np.load(folder / "vectors.npy"), json.loads(meta_path.read_text(encoding="utf-8"))
    by_doc = {d["id"]: d for d in docs}
    grouped = list(section_chunks(chunks).items())
    shards = range(0, len(grouped), SHARD_SECTIONS)
    encoder = None
    seconds, done = 0.0, 0
    vectors: dict[str, NDArray[np.float32]] = {}
    for number, start in enumerate(shards):
        path = folder / f"{number:05d}.npz"
        part = grouped[start : start + SHARD_SECTIONS]
        if not path.exists():
            encoder = encoder or encoder_factory(dense, late)
            began = time.perf_counter()
            sections = [(by_doc[d]["sections"][s]["text"], cs) for (d, s), cs in part]
            encoded = encoder.encode_sections(sections)
            seconds += time.perf_counter() - began
            done += sum(len(cs) for _, cs in part)
            ids = [c["id"] for _, cs in part for c in cs]
            np.savez(path, ids=np.array(ids), vectors=np.concatenate(encoded))
            print(
                f"shard {number + 1}/{len(shards)}: {done / seconds:.1f} chunks/s", file=sys.stderr
            )
        saved = np.load(path)
        vectors.update(zip(saved["ids"].tolist(), saved["vectors"], strict=True))
    matrix = np.asarray([vectors[c["id"]] for c in chunks], dtype=np.float32)
    meta = {
        "fingerprint": fp,
        "method": "late chunking",
        "model": dense.model,
        "max_tokens": late.max_tokens,
        "overlap_tokens": late.overlap_tokens,
        "count": len(chunks),
        "encoded_now": done,
        "encode_seconds": round(seconds, 1),
        "chunks_per_second": round(done / seconds, 2) if seconds else None,
    }
    np.save(folder / "vectors.npy", matrix)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return matrix, meta


def main(argv: list[str] | None = None) -> int:
    from retrieval.dense import connect, load_chunks, load_collection
    from retrieval.dense import load_config as dense_config

    parser = argparse.ArgumentParser(description="Build the late-chunking dense collection")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args(argv)
    dense, late = dense_config(), load_config()
    chunks, sha = load_chunks()
    lines = (CORPUS / "docs.jsonl").read_text(encoding="utf-8").splitlines()
    docs = [json.loads(line) for line in lines]
    vectors, meta = build_vectors(
        dense, late, docs, chunks, sha, lambda d, lc: LateChunkingEncoder(d, lc, args.device)
    )
    target = dense.model_copy(update={"collection": dense.collection + late.collection_suffix})
    report = {**meta, **load_collection(target, connect(), chunks, vectors, meta["fingerprint"])}
    print(json.dumps({k: v for k, v in report.items() if k != "fingerprint"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
