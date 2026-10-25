"""Is the question's subject in the sources? Two deterministic checks (ADR-0018), served by
guidelines-mcp (`check_grounding`) and measured by evals/rag/drug_grounding.py.

- unseen_terms(question): words of 5+ letters (BM25 tokenizer) that the corpus never uses, are not
  common English words (spaCy `en_core_web_md` has no vector for them) and are not a UK/US spelling
  of a corpus word: a drug or term the guidelines cannot be about ("mazdutide").
- missing_drugs(question, cited ids): drugs the question names (DDInter + RxNorm lexicon: names,
  aliases, brands) that no cited source names; another formulation of the same ingredient counts.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from retrieval.bm25 import tokenize
from retrieval.graph.lexicon import DrugLexicon

MIN_CHARS = 5
GRAPH_FACT = "graph:ddinter:"  # DDInter facts are cited as graph:ddinter:<drug a>|<drug b>
SURROGATE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_\d+\b")  # PERSON_1, STREET_ADDRESS_2
SPELLINGS = (
    ("isation", "ization"),
    ("ise", "ize"),
    ("ising", "izing"),
    ("our", "or"),
    ("ae", "e"),
    ("oe", "e"),
)


def spellings(term: str) -> set[str]:
    """British and American spellings of a term (nebulised/nebulized, haemoglobin/hemoglobin)."""
    variants = {term}
    for uk, us in SPELLINGS:
        variants |= {v.replace(uk, us) for v in variants}
    return variants


class Grounding:
    def __init__(
        self,
        chunks: Iterable[Mapping[str, Any]],
        is_english: Callable[[str], bool],
        lexicon: DrugLexicon,
    ) -> None:
        self._texts = {c["id"]: f"{c['title']} {c['section']} {c['text']}" for c in chunks}
        self._df: Counter[str] = Counter()
        for text in self._texts.values():
            self._df.update(set(tokenize(text)))
        self._is_english = is_english
        self._lexicon = lexicon

    def unseen_terms(self, question: str, *, english: bool = True, fold: bool = True) -> list[str]:
        """`english` and `fold` switch the two filters off for the evaluation's variants."""
        terms = []
        for term in tokenize(SURROGATE.sub(" ", question)):  # a de-ID surrogate is not a subject
            if len(term) < MIN_CHARS or not term.isalpha() or self._df[term]:
                continue
            if fold and any(self._df[v] for v in spellings(term)):
                continue
            if english and self._is_english(term):
                continue
            if term not in terms:
                terms.append(term)
        return terms

    def missing_drugs(self, question: str, cited: Iterable[str]) -> list[str]:
        wanted = self._lexicon.find(question)
        if not wanted:
            return []
        found: set[str] = set()
        for cid in cited:
            text = self._texts.get(cid, "")
            if cid.startswith(GRAPH_FACT):
                text = cid.removeprefix(GRAPH_FACT).replace("|", " and ")
            found |= self._lexicon.find(text)
        same = {self._lexicon.identity.get(k, k) for k in found}
        return sorted(
            {
                self._lexicon.names[k]
                for k in wanted
                if k not in found and self._lexicon.identity.get(k, k) not in same
            }
        )
