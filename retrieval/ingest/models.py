"""Normalised corpus records. Every chunk carries what a citation needs: id, source URL, section."""

import hashlib
import re

from pydantic import BaseModel, Field


class Section(BaseModel):
    title: str
    text: str


class Document(BaseModel):
    id: str = Field(
        pattern=r"^[a-z]+:[A-Za-z0-9._/-]+$"
    )  # "who:10665-344424", "pmc:PMC123", "fda:<set_id>"
    source: str  # who | openfda | pmc
    title: str
    url: str
    license: str
    topic: str
    published: str | None = None
    sections: list[Section]


class Chunk(BaseModel):
    id: str  # "<doc id>#s<section>#c<chunk>", stable across rebuilds of the same inputs
    doc_id: str
    source: str
    title: str
    section: str
    url: str
    license: str
    topic: str
    text: str


_SPACE = re.compile(r"\s+")


def normalise_text(text: str) -> str:
    """Collapse whitespace and join words split across PDF lines ("hyper-\\ntension")."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    return _SPACE.sub(" ", text).strip()


# Characters expected in English clinical text; anything else in bulk means a broken PDF font
# encoding (e.g. "'L΍HUHQWLDO" for "Differential").
_EXPECTED = re.compile(
    r"[A-Za-z0-9\s.,;:!?'\"()\[\]{}%/+\-‐–—•·°µ≥≤±×’‘“”=<>&*#@_|~^$€£☐⊕◯αβγδκΔ→←↑↓®™§]"
)


def garbled_share(text: str) -> float:
    """Share of characters outside normal clinical English (0.0 = clean)."""
    if not text:
        return 0.0
    unexpected = sum(1 for ch in text if not _EXPECTED.match(ch))
    return unexpected / len(text)


def content_hash(text: str) -> str:
    return hashlib.sha256(_SPACE.sub(" ", text.lower()).strip().encode()).hexdigest()
