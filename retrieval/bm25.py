"""BM25 keyword search over corpus chunks, in process (ablation step 2).

Okapi BM25 with the non-negative Lucene IDF:
  idf(t) = ln(1 + (N - n_t + 0.5) / (n_t + 0.5))
  score(q, d) = sum over query terms of idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * |d| / L))
where L is the average chunk length in tokens.
It indexes the same chunk text the dense index embeds (no titles), so the ablation compares
retrieval methods, not inputs. The index is rebuilt from data/corpus at start-up (a few seconds).
"""

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import yaml

from privacy.deid.types import DeidentifiedText
from retrieval.dense import Hit

# Small English stop list; clinical words such as "not", "no" and "without" are kept on purpose.
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by", "can", "could",
        "did", "do", "does", "for", "from", "had", "has", "have", "how", "if", "in", "into", "is",
        "it", "its", "may", "might", "of", "on", "or", "should", "so", "such", "than", "that",
        "the", "their", "them", "then", "there", "these", "they", "this", "those", "to", "was",
        "were", "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with",
        "would", "you", "your",
    }
)  # fmt: skip
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens without stopwords; a light plural rule ("inhibitors" ->
    "inhibitor") stands in for a stemmer, applied the same way to queries and chunks."""
    tokens = []
    for token in _TOKEN.findall(text.lower()):
        if token in STOPWORDS:
            continue
        if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
            token = token[:-1]
        tokens.append(token)
    return tokens


class BM25Index:
    def __init__(
        self, chunk_ids: Sequence[str], texts: Sequence[str], k1: float = 1.2, b: float = 0.75
    ) -> None:
        if len(chunk_ids) != len(texts):
            raise ValueError("chunk_ids and texts must have the same length")
        self.chunk_ids = list(chunk_ids)
        self.k1, self.b = k1, b
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        lengths = np.zeros(len(texts), dtype=np.float64)
        for doc, text in enumerate(texts):
            counts = Counter(tokenize(text))
            lengths[doc] = sum(counts.values())
            for term, tf in counts.items():
                postings[term].append((doc, tf))
        self.lengths = lengths
        self.avgdl = float(lengths.mean()) if len(lengths) else 0.0
        n_docs = len(texts)
        self.postings = {
            term: (np.array([d for d, _ in p]), np.array([tf for _, tf in p], dtype=np.float64))
            for term, p in postings.items()
        }
        self.idf = {
            term: math.log(1 + (n_docs - len(p) + 0.5) / (len(p) + 0.5))
            for term, p in postings.items()
        }

    def scores(self, query: str) -> np.ndarray:
        """BM25 score of every chunk for the query (zeros where no query term occurs)."""
        out = np.zeros(len(self.chunk_ids), dtype=np.float64)
        for term in set(tokenize(query)):
            if term not in self.postings:
                continue
            docs, tf = self.postings[term]
            norm = self.k1 * (1 - self.b + self.b * self.lengths[docs] / self.avgdl)
            out[docs] += self.idf[term] * tf * (self.k1 + 1) / (tf + norm)
        return out

    def top(self, query: str, k: int) -> list[Hit]:
        scores = self.scores(query)
        candidates = np.flatnonzero(scores)
        # highest score first; ties broken by corpus order so results are deterministic
        order = candidates[np.lexsort((candidates, -scores[candidates]))][:k]
        return [Hit(chunk_id=self.chunk_ids[i], score=float(scores[i])) for i in order]


class BM25Retriever:
    def __init__(self, index: BM25Index) -> None:
        self._index = index

    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]:
        """Top-k chunks by BM25. Only de-identified text may be searched (ADR-0001)."""
        if not isinstance(query, DeidentifiedText):
            raise TypeError("BM25Retriever.search accepts only DeidentifiedText")
        return self._index.top(query.text, k)


def load_index(corpus: Path | None = None, config: Path | None = None) -> BM25Index:
    """Build the BM25 index from data/corpus/chunks.jsonl with the parameters in
    config/retrieval.yaml."""
    root = Path(__file__).resolve().parents[1]
    corpus = corpus or root / "data" / "corpus"
    cfg = yaml.safe_load((config or root / "config" / "retrieval.yaml").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (corpus / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return BM25Index([r["id"] for r in rows], [r["text"] for r in rows], **cfg["bm25"])
