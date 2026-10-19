"""De-ID with the LoRA name/place tagger (Phase 5) compared with spaCy, on phrasings neither saw.

The tagger: DistilBERT (`distilbert-base-cased`) with a LoRA adapter trained on Colab
(`finetune/deid_ner_lora.ipynb`, adapter in `data/finetune/deid_ner_lora/`). Three variants of the
same analyzer (regex recognisers, context cues and the clinical-term filter are shared):
  spacy  the current de-ID (spaCy `en_core_web_md` for names and places)
  lora   the tagger instead of spaCy
  both   spaCy and the tagger together (any span either finds)
Sets: seeded (the cues were designed on it: optimistic for spacy), held-out v1 (the tagger's
training phrasings were written after seeing v1's misses: optimistic for lora), held-out v2 (written
before the tagger first ran: the fair one), and the 80 PHI-free clinical sentences (over-redaction).

  uv run --with peft==0.21.2 python -m evals.privacy.lora_eval [--round 1|2]
Writes evals/reports/privacy/deid_lora_round<N>.md and .json; the de-ID service is unchanged.
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from presidio_analyzer import EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpArtifacts
from pydantic import SecretStr

from config.settings import Settings
from evals.privacy.clinical_negatives import SENTENCES, SENTENCES_V2
from evals.privacy.corpus import (
    HELDOUT_TEMPLATES,
    HELDOUT_V2_SEED,
    HELDOUT_V2_TEMPLATES,
    HELDOUT_V3_SEED,
    HELDOUT_V3_TEMPLATES,
    NER,
    build,
)
from evals.privacy.deid_eval import leaked
from privacy.deid.engine import Deidentifier, build_analyzer
from privacy.deid.store import InMemoryStore

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "data" / "finetune" / "deid_ner_lora"
REPORT = ROOT / "evals" / "reports" / "privacy" / "deid_lora"
LABELS = ["O", "B-PERSON", "I-PERSON", "B-LOCATION", "I-LOCATION"]
WORD = re.compile(r"[\w'.-]+|[^\w\s]")  # the training data's word split (finetune/make_dataset.py)
SCORE = 0.85  # as spaCy's: context cues (0.88) and exact formats (0.9) still win an overlap


class LoraRecognizer(EntityRecognizer):
    """Names and places from the fine-tuned tagger: word-level BIO tags (the first sub-word's label
    stands for the word, as in training), turned into character spans."""

    def __init__(self, path: Path = ADAPTER) -> None:
        import torch
        from peft import PeftModel  # type: ignore[import-not-found, unused-ignore]
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        config = json.loads((path / "adapter_config.json").read_text(encoding="utf-8"))
        self._torch = torch
        self._tok = AutoTokenizer.from_pretrained(str(path))
        base = AutoModelForTokenClassification.from_pretrained(
            config["base_model_name_or_path"],
            num_labels=len(LABELS),
            id2label=dict(enumerate(LABELS)),
            label2id={label: i for i, label in enumerate(LABELS)},
        )
        self._model = PeftModel.from_pretrained(base, str(path)).eval()
        self._name = "clinscribe-lora"
        super().__init__(supported_entities=list(NER), name=self._name)

    def load(self) -> None:
        return None

    def analyze(
        self, text: str, entities: list[str], nlp_artifacts: NlpArtifacts | None = None
    ) -> list[RecognizerResult]:
        spans = [m.span() for m in WORD.finditer(text)]
        if not spans:
            return []
        encoded = self._tok(
            [text[a:b] for a, b in spans],
            is_split_into_words=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        with self._torch.no_grad():
            best = self._model(**encoded).logits[0].argmax(-1).tolist()
        tags = ["O"] * len(spans)
        seen: set[int] = set()
        for position, word in enumerate(encoded.word_ids(0)):
            if word is not None and word not in seen:
                seen.add(word)
                tags[word] = LABELS[best[position]]
        results: list[RecognizerResult] = []
        kind: str | None = None
        start = end = 0
        for (a, b), tag in [*zip(spans, tags, strict=True), ((len(text), len(text)), "O")]:
            if tag.startswith("I-") and tag[2:] == kind:
                end = b
                continue
            if kind is not None and kind in entities:
                metadata = {RecognizerResult.RECOGNIZER_NAME_KEY: self._name}
                results.append(
                    RecognizerResult(kind, start, end, SCORE, recognition_metadata=metadata)
                )
            kind, start, end = (tag[2:], a, b) if tag != "O" else (None, a, b)
        return results


def evaluate(deidentifier: Deidentifier) -> dict[str, Any]:
    sets = {
        "seeded": build(),
        "heldout_v1": build(n=100, seed=7, templates=HELDOUT_TEMPLATES),
        "heldout_v2": build(n=100, seed=HELDOUT_V2_SEED, templates=HELDOUT_V2_TEMPLATES),
        "heldout_v3": build(n=100, seed=HELDOUT_V3_SEED, templates=HELDOUT_V3_TEMPLATES),
    }
    out: dict[str, Any] = {}
    latencies: list[float] = []
    for name, snippets in sets.items():
        totals: Counter[str] = Counter()
        caught: Counter[str] = Counter()
        for i, snippet in enumerate(snippets):
            started = time.perf_counter()
            text = deidentifier.deidentify(snippet.text, encounter_id=f"{name}-{i}").text.text
            latencies.append((time.perf_counter() - started) * 1000)
            for entity, value in snippet.phi:
                if entity in NER:
                    totals[entity] += 1
                    caught[entity] += not leaked(entity, value, text)
        out[name] = {e: (caught[e], totals[e]) for e in NER if totals[e]}
    for key, sentences in (("negatives_v1", SENTENCES), ("negatives_v2", SENTENCES_V2)):
        altered = [
            sentence
            for i, sentence in enumerate(sentences)
            if deidentifier.deidentify(sentence, encounter_id=f"{key}-{i}").replacements
        ]
        out[key] = (len(altered), len(sentences))
        out[f"{key}_altered"] = altered
    latencies.sort()
    out["latency_ms"] = (
        latencies[len(latencies) // 2],
        latencies[max(0, int(len(latencies) * 0.95) - 1)],
    )
    return out


SET_LABELS = {
    "seeded": "seeded",
    "heldout_v1": "held-out v1",
    "heldout_v2": "held-out v2",
    "heldout_v3": "held-out v3",
}
FAIRNESS = {
    1: "Fair sets for round 1: held-out v2 and v3, PHI-free v1 and v2. Seeded flatters spaCy (the "
    "cues were designed on it); held-out v1 flatters the tagger (its training phrasings were "
    "written after v1's misses).",
    2: "Fair sets for round 2: **held-out v3 and PHI-free v2** (written before round 2 was "
    "trained). Round 2's data was written knowing held-out v2 and which PHI-free v1 sentences "
    "round 1 altered, so those two flatter it; seeded and held-out v1 as for round 1.",
}


def report(results: dict[str, dict[str, Any]], round_: int) -> str:
    def cell(counts: tuple[int, int]) -> str:
        hit, total = counts
        return f"{hit / total:.3f} ({hit}/{total})"

    lines = [
        f"# De-ID: LoRA name/place tagger (round {round_}) vs spaCy",
        "",
        "Generated by `evals/privacy/lora_eval.py`. Recall = the share of seeded names and places",
        "with no word left in the output (same check as `deid_eval.py`). Synthetic data only.",
        FAIRNESS[round_],
        "",
        "| Variant | Set | PERSON | LOCATION |",
        "|---|---|---|---|",
    ]
    for variant, out in results.items():
        for name, label in SET_LABELS.items():
            lines.append(
                f"| {variant} | {label} | {cell(out[name]['PERSON'])} | "
                f"{cell(out[name]['LOCATION'])} |"
            )
    lines += [
        "",
        "| Variant | PHI-free v1 altered | PHI-free v2 altered | Latency p50 / p95 |",
        "|---|---|---|---|",
    ]
    for variant, out in results.items():
        (n1, t1), (n2, t2) = out["negatives_v1"], out["negatives_v2"]
        p50, p95 = out["latency_ms"]
        lines.append(
            f"| {variant} | {n1} of {t1} | {n2} of {t2} | {p50:.1f} / {p95:.1f} ms per snippet |"
        )
    lines += ["", "Altered PHI-free sentences (any change damages the clinical meaning):", ""]
    for variant, out in results.items():
        for key in ("negatives_v1", "negatives_v2"):
            for sentence in out[f"{key}_altered"]:
                lines.append(f"- {variant}, {key.replace('negatives_', 'PHI-free ')}: {sentence}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--round", dest="round_", type=int, choices=(1, 2), default=1)
    parser.add_argument("--adapter", type=Path, help="default: data/finetune/deid_ner_lora[_v2]")
    args = parser.parse_args(argv)
    adapter = args.adapter or (
        ADAPTER if args.round_ == 1 else ADAPTER.with_name("deid_ner_lora_v2")
    )
    settings = Settings()
    lora = LoraRecognizer(adapter)
    variants = {
        "spacy": build_analyzer(settings.deid_spacy_model),
        "lora": build_analyzer(settings.deid_spacy_model, spacy_ner=False, extra=[lora]),
        "both": build_analyzer(settings.deid_spacy_model, extra=[lora]),
    }
    results = {}
    for name, analyzer in variants.items():
        store = InMemoryStore(SecretStr(Fernet.generate_key().decode()))  # throwaway
        results[name] = evaluate(Deidentifier(analyzer, store))
        summary = {k: v for k, v in results[name].items() if not k.endswith("_altered")}
        print(name, summary, flush=True)
    path = REPORT.with_name(f"{REPORT.name}_round{args.round_}")
    path.with_suffix(".json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    path.with_suffix(".md").write_text(report(results, args.round_), encoding="utf-8")
    print(f"wrote {path.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
