"""WHO guidelines from IRIS (DSpace REST API). CC BY-NC-SA 3.0 IGO, verified per item.

Sections come from the PDF's outline (bookmarks): each entry's text runs from its page to the next
entry's page. Without an outline, each page becomes a section. Front and back matter is skipped.
"""

import json
import re
from pathlib import Path

import httpx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from retrieval.ingest.models import Document, Section, normalise_text

IRIS = "https://iris.who.int/server/api"
SKIP_SECTION = re.compile(
    r"^(contents|table of contents|foreword|preface|acknowledg|abbreviations|acronyms|glossary|"
    r"references|bibliography|declarations? of interest|copyright|index|web annex)",
    re.IGNORECASE,
)


def _item(client: httpx.Client, handle: str) -> dict[str, object]:
    response = client.get(f"{IRIS}/pid/find", params={"id": handle})
    response.raise_for_status()
    data: dict[str, object] = response.json()
    return data


def _meta(item: dict[str, object], key: str) -> str | None:
    values = item.get("metadata", {}).get(key) or []  # type: ignore[attr-defined]
    return str(values[0]["value"]) if values else None


def _pdf_url(client: httpx.Client, item: dict[str, object]) -> str:
    bundles_href = item["_links"]["bundles"]["href"]  # type: ignore[index]
    for bundle in client.get(bundles_href).json()["_embedded"]["bundles"]:
        if bundle["name"] != "ORIGINAL":
            continue
        for bitstream in client.get(bundle["_links"]["bitstreams"]["href"]).json()["_embedded"][
            "bitstreams"
        ]:
            if bitstream["name"].lower().endswith(".pdf"):
                return str(bitstream["_links"]["content"]["href"])
    raise LookupError("no PDF bitstream in the ORIGINAL bundle")


EDGE_LINES = 2  # headers and footers live in the first/last two lines of a page

# Glyphs whose meaning is certain from context in the WHO PDFs (checked 2026-10-06):
# GRADE evidence-to-decision checkboxes and certainty symbols ("Moderate ⊕⊕⊕◯"), and the "ff"
# ligature in the offset-encoded PEN text ("(Ύective" = "Effective", "diΎerent" = "different").
KNOWN_GLYPHS = {
    "": "☐", "": "⊕", "": "◯",  # GRADE tables ("Moderate ⊕⊕⊕◯")
    "": "•", "": " ",  # Symbol-font bullet and space ("• To consider ...")
    **{chr(0xF030 + d): str(d) for d in range(10)},  # Symbol-font digits in table cells
}  # fmt: skip
# Lines carrying this AWaRe-book marker glyph are running chapter headers: dropped whole.
HEADER_MARKER = ""
# Each confirmed by real words in the PEN text: "(Ύective" = "Effective", "ȴQG" = "find",
# "LQGLYLGXDOȇV" = "individual's". Other glyphs (e.g. the one before "130/80 mmHg") stay "[?]".
OFFSET_LIGATURES = {"΍": "ff", "ȴ": "fi", "ȇ": "'"}
FONT_OFFSET = 29  # PEN 2020 subset font: character code = Unicode code point - 29
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f]")


def _decode_offset_token(token: str) -> str:
    out = []
    for ch in token:
        if ch in OFFSET_LIGATURES:
            out.append(OFFSET_LIGATURES[ch])
        elif ord(ch) <= 0x7E - FONT_OFFSET:
            out.append(chr(ord(ch) + FONT_OFFSET))
        elif ch.isascii():
            out.append(ch)  # real text glued to an offset run (chart labels): keep as-is
        else:
            out.append("[?]")  # an unmapped glyph: never guess (e.g. a BP threshold symbol)
    return "".join(out)


def repair_text(text: str) -> str:
    """Undo two PDF font problems: offset-encoded tokens and private-use symbol glyphs.

    Offset-encoded text ("SHUVLVWHQW\\x03%3" = "persistent BP") uses control characters for its
    spaces, which normal text never contains, so only space-separated tokens with a control
    character are decoded; the rest of the text is left untouched.
    """
    for glyph, meaning in KNOWN_GLYPHS.items():
        text = text.replace(glyph, meaning)
    tokens = [_decode_offset_token(t) if _CONTROL.search(t) else t for t in text.split(" ")]
    text = " ".join(tokens)
    return re.sub(r"[-]", "[?]", text)  # any other private-use glyph


def page_text(raw: str) -> str:
    """Repair one page. Split on "\\n" only: str.splitlines() also breaks on \\x1c-\\x1e, which
    in the offset-encoded font are the digit 9, ':' and ';' (it silently turned 140/90 into 140/0).
    """
    lines = [line for line in raw.split("\n") if HEADER_MARKER not in line]
    return "\n".join(repair_text(line) for line in lines)


def strip_running_lines(pages: list[str], min_share: float = 0.3) -> list[str]:
    """Remove running headers/footers: edge lines (digits normalised) on >= min_share of pages.

    "36The WHO AWaRe (Access, Watch, Reserve) antibiotic book" repeats on hundreds of pages and
    would otherwise sit inside many chunks. Only the first and last EDGE_LINES lines of a page are
    candidates, so repeated real content ("Strength of recommendation: strong") is kept.
    Bare page numbers at the edges are removed too.
    """
    if len(pages) < 5:
        return pages

    def key(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip().lower())

    def edges(lines: list[str]) -> set[int]:
        n = len(lines)
        return set(range(min(EDGE_LINES, n))) | set(range(max(0, n - EDGE_LINES), n))

    page_lines = [[line for line in page.splitlines() if line.strip()] for page in pages]
    counts: dict[str, int] = {}
    for lines in page_lines:
        for line_key in {key(lines[i]) for i in edges(lines)}:
            counts[line_key] = counts.get(line_key, 0) + 1
    running = {k for k, n in counts.items() if n >= min_share * len(pages)}

    cleaned = []
    for lines in page_lines:
        edge = edges(lines)
        kept = [
            line
            for i, line in enumerate(lines)
            if not (i in edge and (key(line) in running or re.fullmatch(r"\s*\d{1,4}\s*", line)))
        ]
        cleaned.append("\n".join(kept))
    return cleaned


def sections_from_outline(outline: list[tuple[str, int]], pages: list[str]) -> list[Section]:
    """Turn (title, start page) outline entries into sections covering page ranges."""
    if not outline:
        return [
            Section(title=f"Page {i + 1}", text=normalise_text(text))
            for i, text in enumerate(pages)
            if text.strip()
        ]
    ordered = sorted(outline, key=lambda entry: entry[1])
    sections = []
    for i, (title, start) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else len(pages)
        if SKIP_SECTION.match(title.strip()):
            continue
        text = normalise_text("\n".join(pages[start : max(end, start + 1)]))
        if text:
            sections.append(Section(title=normalise_text(title), text=text))
    return sections


def _flatten_outline(
    reader: PdfReader, entries: list[object], depth: int = 0
) -> list[tuple[str, int]]:
    flat: list[tuple[str, int]] = []
    for entry in entries:
        if isinstance(entry, list):
            if depth < 1:  # chapters and their first-level subsections
                flat += _flatten_outline(reader, entry, depth + 1)
            continue
        try:
            page = reader.get_destination_page_number(entry)  # type: ignore[arg-type]
        except (KeyError, ValueError, TypeError, PdfReadError):
            page = None  # malformed bookmark
        if page is not None and page >= 0:
            flat.append((str(entry.title), page))  # type: ignore[attr-defined]
    return flat


def fetch(client: httpx.Client, handle: str, topic: str, raw_dir: Path) -> Document:
    raw_dir.mkdir(parents=True, exist_ok=True)
    item_path = raw_dir / f"{handle.replace('/', '-')}.json"
    if item_path.exists():
        item = json.loads(item_path.read_text(encoding="utf-8"))
    else:
        item = _item(client, handle)
        item_path.write_text(json.dumps(item), encoding="utf-8")
    pdf_path = raw_dir / f"{handle.replace('/', '-')}.pdf"
    if not pdf_path.exists():
        with client.stream("GET", _pdf_url(client, item)) as response:
            response.raise_for_status()
            with pdf_path.open("wb") as out:
                for block in response.iter_bytes(1 << 20):
                    out.write(block)
    reader = PdfReader(pdf_path)
    pages = strip_running_lines([page_text(page.extract_text() or "") for page in reader.pages])
    outline = _flatten_outline(reader, list(reader.outline))
    return Document(
        id=f"who:{handle.replace('/', '-')}",
        source="who",
        title=str(item.get("name")),
        url=f"https://iris.who.int/handle/{handle}",
        license=_meta(item, "dc.rights") or "CC BY-NC-SA 3.0 IGO",
        topic=topic,
        published=_meta(item, "dc.date.issued"),
        sections=sections_from_outline(outline, pages),
    )
