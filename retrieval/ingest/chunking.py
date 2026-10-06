"""Section-aware chunking: chunks never cross a section boundary, so each cites one section.

Splits on sentence boundaries into ~target_words chunks with overlap_words of overlap. Word counts
keep chunking independent of the embedding model's tokenizer (~1.3 tokens per English word).
"""

import re

from retrieval.ingest.models import Chunk, Document

_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+(?=[A-Z0-9(\[\"'•-])")


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text) if s.strip()]


def _windows(sentences: list[str], target: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        words = len(sentence.split())
        if current and count + words > target:
            chunks.append(" ".join(current))
            # carry the last sentences (up to `overlap` words) into the next chunk
            carried: list[str] = []
            carried_words = 0
            for previous in reversed(current):
                n = len(previous.split())
                if carried_words + n > overlap:
                    break
                carried.insert(0, previous)
                carried_words += n
            current, count = carried, carried_words
        current.append(sentence)
        count += words
    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_document(doc: Document, target: int, overlap: int, min_words: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for s_idx, section in enumerate(doc.sections):
        sentences = split_sentences(section.text)
        # a single over-long "sentence" (tables, lists) is hard-split on words
        expanded: list[str] = []
        for sentence in sentences:
            words = sentence.split()
            if len(words) <= target:
                expanded.append(sentence)
            else:
                expanded += [" ".join(words[i : i + target]) for i in range(0, len(words), target)]
        for c_idx, text in enumerate(_windows(expanded, target, overlap)):
            if len(text.split()) < min_words:
                continue
            chunks.append(
                Chunk(
                    id=f"{doc.id}#s{s_idx}#c{c_idx}",
                    doc_id=doc.id,
                    source=doc.source,
                    title=doc.title,
                    section=section.title,
                    url=doc.url,
                    license=doc.license,
                    topic=doc.topic,
                    text=text,
                )
            )
    return chunks
