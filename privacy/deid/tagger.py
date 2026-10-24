"""Names and places from the fine-tuned token tagger (ADR-0014), as a Presidio recogniser.

DistilBERT (`distilbert-base-cased`) with a LoRA adapter trained on synthetic clinical speech
(`finetune/`), merged into one model (`finetune/merge.py`, `data/finetune/deid_ner_tagger/`), so
only transformers and torch are needed at run time. Chosen over spaCy on unseen phrasings: places
recall 1.000 vs 0.840 with fewer PHI-free sentences altered (evals/reports/privacy/
deid_lora_round2.md). Used when `DEID_NER=tagger`; spaCy stays the default.

The text is split into words exactly as the training data was (`[\\w'.-]+|[^\\w\\s]`); the first
sub-word's label stands for its word, as in training; long texts are tagged in windows of words,
and a window the token limit cuts short continues at the first word left out.
"""

import re
from pathlib import Path
from typing import Any

from presidio_analyzer import EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpArtifacts

LABELS = ["O", "B-PERSON", "I-PERSON", "B-LOCATION", "I-LOCATION"]
WORD = re.compile(r"[\w'.-]+|[^\w\s]")
WINDOW = 200  # words per model call: usually well under the token limit for clinical speech
MAX_TOKENS = 512  # DistilBERT's limit (the saved tokenizer config also records 128 from training)
SCORE = 0.85  # as spaCy's: context cues (0.88) and exact formats (0.9) still win an overlap
NAME = "clinscribe-tagger"


def bio_spans(words: list[tuple[int, int]], tags: list[str]) -> list[tuple[str, int, int]]:
    """(type, start, end) character spans from per-word BIO tags. An I- tag that does not continue
    an entity of its type starts a new one (as seqeval's default mode)."""
    spans: list[tuple[str, int, int]] = []
    kind: str | None = None
    start = end = 0
    for (a, b), tag in [*zip(words, tags, strict=True), ((-1, -1), "O")]:
        if tag.startswith("I-") and tag[2:] == kind:
            end = b
            continue
        if kind is not None:
            spans.append((kind, start, end))
        kind, start, end = (tag[2:], a, b) if tag != "O" else (None, a, b)
    return spans


class TaggerRecognizer(EntityRecognizer):
    def __init__(self, path: str | Path) -> None:
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        self._torch: Any = torch
        self._tok: Any = AutoTokenizer.from_pretrained(str(path))
        self._model: Any = AutoModelForTokenClassification.from_pretrained(str(path)).eval()
        super().__init__(supported_entities=["PERSON", "LOCATION"], name=NAME)

    def load(self) -> None:
        return None

    def tags(self, words: list[str]) -> list[str]:
        """One label per word. A window that the token limit cuts short goes on from the first word
        left out, so no word is ever labelled without being seen (an unseen name would leak)."""
        out: list[str] = []
        while len(out) < len(words):
            chunk = words[len(out) : len(out) + WINDOW]
            encoded = self._tok(
                chunk,
                is_split_into_words=True,
                truncation=True,
                max_length=MAX_TOKENS,
                return_tensors="pt",
            )
            with self._torch.no_grad():
                best = self._model(**encoded).logits[0].argmax(-1).tolist()
            labels: list[str] = []
            for position, word in enumerate(encoded.word_ids(0)):
                if word is not None and word == len(labels):  # first sub-word of the next word
                    labels.append(LABELS[best[position]])
            if not labels:
                raise RuntimeError("the tagger saw no word of a window")
            out += labels
        return out

    def analyze(
        self, text: str, entities: list[str], nlp_artifacts: NlpArtifacts | None = None
    ) -> list[RecognizerResult]:
        words = [m.span() for m in WORD.finditer(text)]
        if not words:
            return []
        tags = self.tags([text[a:b] for a, b in words])
        metadata = {RecognizerResult.RECOGNIZER_NAME_KEY: NAME}
        return [
            RecognizerResult(kind, start, end, SCORE, recognition_metadata=dict(metadata))
            for kind, start, end in (
                (kind, start, trim_full_stop(text, start, end))
                for kind, start, end in bio_spans(words, tags)
            )
            if kind in entities
        ]


def trim_full_stop(text: str, start: int, end: int) -> int:
    """The word split keeps a dot inside a word ("Dr.", as in training), so "...to Denver." makes
    "Denver." one word; a span must not take the sentence's full stop with it. An initial ("J.")
    keeps its dot."""
    if end - start > 2 and text[end - 1] == "." and not text[end - 2].isupper():
        return end - 1
    return end
