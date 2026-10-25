"""Citation support, offline (SPEC section 6, citation grounding): can a small local NLI model tell
the citations that support their sentence from those that do not?

Every (sentence, cited chunk) link the Phase 2 judge rated (`evals/reports/rag/answers/*.jsonl`:
"supports", "partial" or "no") is scored with each model: the probability that the chunk entails
the sentence, from the whole chunk or from its best 2-sentence window (SummaC style: NLI models
are trained on short premises). Two pruning policies (POLICIES) use a threshold chosen by 2-fold
cross-validation over questions (a question and its answers from all three pipelines stay in one
fold), as the lowest that reaches citation precision 0.95 on the other fold. No LLM calls; the
judge's ratings are the labels.

  uv run python -m evals.rag.citation_support
Writes evals/reports/rag/citation_support.{md,json}.
"""

import json
import math
import random
import re
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANSWERS = ROOT / "evals" / "reports" / "rag" / "answers"
CORPUS = ROOT / "data" / "corpus"
REPORT = ROOT / "evals" / "reports" / "rag" / "citation_support"
PIPELINES = ("dense", "hybrid_colbert", "hybrid_colbert_ctx")
TARGET = 0.95  # SPEC section 1: citation precision
SEED = 20261025
TEXT_FIELDS = ("premise", "heading", "text")  # not written to the report
# Apache-2.0, safetensors, no remote code, pinned; labels: contradiction, entailment, neutral
MODELS = {
    "nli-deberta-v3-xsmall": (
        "cross-encoder/nli-deberta-v3-xsmall",
        "a150876415327c80daeff35ca6f68f5ed8cf5c24",
    ),
    "nli-deberta-v3-small": (
        "cross-encoder/nli-deberta-v3-small",
        "fa2804872c3b4bd748f38c0185cc85775361e735",
    ),
    "nli-MiniLM2-L6-H768": (
        "cross-encoder/nli-MiniLM2-L6-H768",
        "b95119ce93d3e065de6214e38cd4a97b0f2f2c6d",
    ),
}
ENTAILMENT = 1
# SummaC-style: NLI models are trained on short premises, so a long chunk is also scored as windows
# of WINDOW sentences (stride 1) and the link gets its best window
WINDOW = 2
SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9(])")


@dataclass
class Link:
    pipeline: str
    question: str
    sentence: int  # 1-based, within the answer
    chunk_id: str
    rating: str  # supports | partial | no
    hypothesis: str  # the answer sentence
    premise: str  # "title — section. text" as the generator and the judge saw it
    heading: str  # "title — section. "
    text: str


def load_links() -> list[Link]:
    docs = {
        d["id"]: d for d in map(json.loads, (CORPUS / "docs.jsonl").read_text("utf-8").splitlines())
    }
    chunks = {
        c["id"]: c
        for c in map(json.loads, (CORPUS / "chunks.jsonl").read_text("utf-8").splitlines())
    }
    links: list[Link] = []
    for pipeline in PIPELINES:
        for line in (ANSWERS / f"{pipeline}.jsonl").read_text("utf-8").splitlines():
            row = json.loads(line)
            if row["answer"]["abstained"] or not row.get("judgment"):
                continue
            label_to_chunk = {f"S{i}": cid for i, cid in enumerate(row["chunk_ids"], start=1)}
            for judged in row["judgment"]["sentences"]:
                sentence = row["answer"]["sentences"][judged["n"] - 1]
                for label, rating in judged["cited"].items():
                    chunk = chunks[label_to_chunk[label]]
                    title = docs[chunk["doc_id"]]["title"]
                    links.append(
                        Link(
                            pipeline=pipeline,
                            question=row["id"],
                            sentence=judged["n"],
                            chunk_id=chunk["id"],
                            rating=rating,
                            hypothesis=sentence["text"],
                            premise=f"{title} — {chunk['section']}. {chunk['text']}",
                            heading=f"{title} — {chunk['section']}. ",
                            text=chunk["text"],
                        )
                    )
    return links


def softmax_entailment(logits: Sequence[float]) -> float:
    peak = max(logits)
    exps = [math.exp(x - peak) for x in logits]
    return exps[ENTAILMENT] / sum(exps)


def windows(link: Link) -> list[str]:
    sentences = [s for s in SENTENCE_END.split(link.text) if s.strip()] or [link.text]
    spans = [sentences[i : i + WINDOW] for i in range(max(1, len(sentences) - WINDOW + 1))]
    return [link.heading + " ".join(span) for span in spans]


def score(links: list[Link], name: str, windowed: bool = False) -> tuple[list[float], list[float]]:
    """Entailment probability per link (the whole chunk, or its best window), and the CPU time
    per answer (all its links in one batch)."""
    from sentence_transformers import CrossEncoder

    model_id, revision = MODELS[name]
    model = CrossEncoder(model_id, revision=revision, max_length=512, device="cpu")
    by_answer: dict[tuple[str, str], list[int]] = {}
    for i, link in enumerate(links):
        by_answer.setdefault((link.pipeline, link.question), []).append(i)
    scores = [0.0] * len(links)
    seconds: list[float] = []
    model.predict([(links[0].premise, links[0].hypothesis)])  # warm-up
    for indexes in by_answer.values():
        owner: list[int] = []
        pairs = []
        for i in indexes:
            premises = windows(links[i]) if windowed else [links[i].premise]
            pairs += [(premise, links[i].hypothesis) for premise in premises]
            owner += [i] * len(premises)
        start = time.perf_counter()
        logits = model.predict(pairs, batch_size=16, convert_to_numpy=True)
        seconds.append(time.perf_counter() - start)
        for i in indexes:
            scores[i] = 0.0
        for i, row in zip(owner, logits, strict=True):
            scores[i] = max(scores[i], softmax_entailment([float(x) for x in row]))
    return scores, seconds


def auc(scores: list[float], positive: list[bool]) -> float:
    """Probability that a supported link scores above an unsupported one (ties count half)."""
    pos = [s for s, p in zip(scores, positive, strict=True) if p]
    neg = [s for s, p in zip(scores, positive, strict=True) if not p]
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def precision(kept: list[bool], positive: list[bool]) -> float:
    n = sum(kept)
    return sum(k and p for k, p in zip(kept, positive, strict=True)) / n if n else 1.0


# "threshold": keep a link whose score reaches t; a sentence left with no citation is dropped.
# "best kept": every sentence keeps its best-scoring citation, the others only if they reach t, so
# no sentence is dropped (aimed at over-attribution: a second source that only partly supports).
POLICIES = ("threshold", "best kept")


def keep(scores: list[float], best: list[bool], t: float, policy: str) -> list[bool]:
    return [s >= t or (policy == "best kept" and b) for s, b in zip(scores, best, strict=True)]


def pick_threshold(
    scores: list[float], best: list[bool], positive: list[bool], policy: str
) -> float:
    """The lowest threshold whose kept links reach TARGET precision (else the most precise one);
    1.01 keeps no link on its score alone."""
    chosen, chosen_precision = 1.01, -1.0
    for t in [*sorted(set(scores)), 1.01]:
        p = precision(keep(scores, best, t, policy), positive)
        if p >= TARGET:
            return t
        if p > chosen_precision:
            chosen, chosen_precision = t, p
    return chosen


def folds(links: list[Link]) -> list[int]:
    questions = sorted({link.question for link in links})
    random.Random(SEED).shuffle(questions)
    fold_of = {q: i % 2 for i, q in enumerate(questions)}
    return [fold_of[link.question] for link in links]


def best_in_sentence(links: list[Link], scores: list[float]) -> list[bool]:
    top: dict[tuple[str, str, int], int] = {}
    for i, link in enumerate(links):
        key = (link.pipeline, link.question, link.sentence)
        if key not in top or scores[i] > scores[top[key]]:
            top[key] = i
    winners = set(top.values())
    return [i in winners for i in range(len(links))]


def evaluate(links: list[Link], scores: list[float]) -> dict[str, object]:
    positive = [link.rating == "supports" for link in links]
    best = best_in_sentence(links, scores)
    fold = folds(links)
    policies: dict[str, object] = {}
    for policy in POLICIES:
        kept = [False] * len(links)
        thresholds = []
        for test in (0, 1):
            train = [i for i, f in enumerate(fold) if f != test]
            t = pick_threshold(
                [scores[i] for i in train],
                [best[i] for i in train],
                [positive[i] for i in train],
                policy,
            )
            thresholds.append(round(t, 4))
            for i, f in enumerate(fold):
                if f == test:
                    kept[i] = keep([scores[i]], [best[i]], t, policy)[0]
        policies[policy] = {
            "thresholds": thresholds,
            "pipelines": {name: summary(links, kept, positive, name) for name in PIPELINES},
        }
    return {"auc": round(auc(scores, positive), 3), "policies": policies}


def summary(
    links: list[Link], kept: list[bool], positive: list[bool], pipeline: str
) -> dict[str, object]:
    idx = [i for i, link in enumerate(links) if link.pipeline == pipeline]
    sentences: dict[tuple[str, int], list[int]] = {}
    for i in idx:
        sentences.setdefault((links[i].question, links[i].sentence), []).append(i)
    dropped = [s for s, ids in sentences.items() if not any(kept[i] for i in ids)]
    supported = {s for s, ids in sentences.items() if any(positive[i] for i in ids)}
    answers = {q for q, _ in sentences}
    emptied = [q for q in answers if all(s in dropped for s in sentences if s[0] == q)]
    good = [i for i in idx if positive[i]]
    bad = [i for i in idx if not positive[i]]
    return {
        "links": len(idx),
        "precision_before": round(precision([True] * len(idx), [positive[i] for i in idx]), 3),
        "precision_after": round(precision([kept[i] for i in idx], [positive[i] for i in idx]), 3),
        "supported_links_kept": round(sum(kept[i] for i in good) / max(1, len(good)), 3),
        "unsupported_links_dropped": round(sum(not kept[i] for i in bad) / max(1, len(bad)), 3),
        "sentences": len(sentences),
        "sentences_dropped": len(dropped),
        "supported_sentences_dropped": len([s for s in dropped if s in supported]),
        "answers_emptied": len(emptied),
        "answers": len(answers),
    }


def main() -> int:
    links = load_links()
    ratings = {r: sum(link.rating == r for link in links) for r in ("supports", "partial", "no")}
    results: dict[str, object] = {"links": len(links), "ratings": ratings, "models": {}}
    for name, windowed in [(m, w) for m in MODELS for w in (False, True)]:
        scores, seconds = score(links, name, windowed)
        name = f"{name}, {WINDOW}-sentence windows" if windowed else f"{name}, whole chunk"
        outcome = evaluate(links, scores)
        outcome["seconds_per_answer"] = {
            "p50": round(statistics.median(seconds), 3),
            "p95": round(sorted(seconds)[int(0.95 * (len(seconds) - 1))], 3),
        }
        outcome["link_scores"] = [
            # ids and ratings only: chunk text stays in data/ (WHO text is CC BY-NC-SA)
            {
                **{k: v for k, v in asdict(link).items() if k not in TEXT_FIELDS},
                "score": round(s, 4),
            }
            for link, s in zip(links, scores, strict=True)
        ]
        results["models"][name] = outcome  # type: ignore[index]
        print(name, json.dumps({k: v for k, v in outcome.items() if k != "link_scores"}))
    REPORT.with_suffix(".json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    REPORT.with_suffix(".md").write_text(render(results), encoding="utf-8")
    return 0


def render(results: dict[str, object]) -> str:
    models: dict[str, dict[str, object]] = results["models"]  # type: ignore[assignment]
    ratings: dict[str, int] = results["ratings"]  # type: ignore[assignment]
    lines = [
        "# Citation support: a local NLI check on the Phase 2 answers",
        "",
        "Generated by `evals/rag/citation_support.py` (no LLM calls). Labels: the Phase 2 judge's",
        f"rating of each (sentence, cited chunk) link, {results['links']} links: "
        + ", ".join(f"{v} {k}" for k, v in ratings.items())
        + '. Precision = share of kept links rated "supports" (pooled over links).',
        "Score = entailment probability, from the whole chunk or its best "
        f"{WINDOW}-sentence window. Policies: *threshold* keeps",
        "links that reach t and drops sentences left uncited; *best kept* keeps every sentence's",
        "best-scoring citation and the others only if they reach t. t is chosen on the other half",
        f"of the questions (2-fold, seed {SEED}) as the lowest that reaches precision {TARGET}.",
        "",
        "| Model | AUC | CPU s per answer p50 / p95 | t (threshold) | t (best kept) |",
        "|---|---|---|---|---|",
    ]
    for name, m in models.items():
        sec: dict[str, float] = m["seconds_per_answer"]  # type: ignore[assignment]
        pol: dict[str, dict[str, object]] = m["policies"]  # type: ignore[assignment]
        lines.append(
            f"| {name} | {m['auc']} | {sec['p50']} / {sec['p95']} | "
            f"{pol['threshold']['thresholds']} | {pol['best kept']['thresholds']} |"
        )
    lines += [
        "",
        "| Model | Policy | Pipeline | Precision before → after | Supported links kept | "
        "Unsupported dropped | Sentences dropped (judge-supported) | Answers emptied |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, m in models.items():
        policies: dict[str, dict[str, object]] = m["policies"]  # type: ignore[assignment]
        for policy, outcome in policies.items():
            per: dict[str, dict[str, object]] = outcome["pipelines"]  # type: ignore[assignment]
            for pipeline, r in per.items():
                lines.append(
                    f"| {name} | {policy} | {pipeline} | {r['precision_before']} → "
                    f"{r['precision_after']} | {r['supported_links_kept']} | "
                    f"{r['unsupported_links_dropped']} | {r['sentences_dropped']} of "
                    f"{r['sentences']} ({r['supported_sentences_dropped']}) | "
                    f"{r['answers_emptied']} of {r['answers']} |"
                )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
