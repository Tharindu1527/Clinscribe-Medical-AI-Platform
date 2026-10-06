"""PubMed Central review articles (JATS XML via NCBI E-utilities). CC BY and CC0 only.

The licence is read from each article's own <license> element; anything else (CC BY-NC, custom,
none) is skipped even if the search filter let it through. No e-mail is sent to NCBI.
"""

import re
import time
import xml.etree.ElementTree as ET  # types only; parsing uses defusedxml
from pathlib import Path

import httpx
from defusedxml.ElementTree import fromstring as safe_fromstring

from retrieval.ingest.models import Document, Section, normalise_text

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_PAUSE_S = 0.4  # NCBI asks for at most 3 requests per second without an API key
XLINK = "{http://www.w3.org/1999/xlink}href"
NOT_HUMAN_TITLE_WORDS = (
    "equine",
    "horse",
    "horses",
    "canine",
    "dog",
    "dogs",
    "feline",
    "cat",
    "cats",
    "bovine",
    "cattle",
    "veterinary",
    "animal",
    "animals",
    "murine",
    "mouse",
    "mice",
    "rat",
    "rats",
)
SKIP_SECTION = re.compile(
    r"^(references|acknowledg|conflicts? of interest|competing interests|funding|author contrib|"
    r"supplementary|abbreviations|data availability|ethics|declarations?|disclosure)",
    re.IGNORECASE,
)


def licence_of(article: ET.Element) -> str | None:
    """'CC BY 4.0'-style label for CC BY or CC0 articles; None for anything else."""
    for lic in article.iter():
        if not lic.tag.endswith("license") and not lic.tag.endswith("license_ref"):
            continue
        href = (lic.get(XLINK) or "") + " " + "".join(lic.itertext())
        if "publicdomain/zero" in href:
            return "CC0 1.0"
        match = re.search(r"creativecommons\.org/licenses/by/(\d\.\d)", href)
        if match:
            return f"CC BY {match.group(1)}"
    return None


FORMULA_TAGS = ("inline-formula", "disp-formula")


def _plain(element: ET.Element) -> str:
    """Element text with formulas replaced by "[formula]" (their LaTeX/MathML source is noise)."""
    if element.tag.split("}")[-1] in FORMULA_TAGS:
        return " [formula] " + (element.tail or "")
    parts = [element.text or ""]
    for child in element:
        parts.append(_plain(child))
    parts.append(element.tail or "")
    return "".join(parts)


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return normalise_text(_plain(element).removesuffix(element.tail or ""))


def _sections(sec: ET.Element, prefix: str = "") -> list[Section]:
    title = _text(sec.find("title")) or "Untitled section"
    full_title = f"{prefix} > {title}" if prefix else title
    if SKIP_SECTION.match(title):
        return []
    paragraphs = [_text(p) for p in sec.findall("p")]
    found = (
        [Section(title=full_title, text=" ".join(p for p in paragraphs if p))]
        if any(paragraphs)
        else []
    )
    for child in sec.findall("sec"):
        found += _sections(child, full_title)
    return found


def parse_article(article: ET.Element, topic: str) -> Document | None:
    licence = licence_of(article)
    body = article.find(".//body")
    if licence is None or body is None:
        return None
    meta = article.find(".//article-meta")
    pmcid = ""
    for article_id in meta.findall("article-id") if meta is not None else []:
        if article_id.get("pub-id-type") in ("pmc", "pmcid"):
            pmcid = (article_id.text or "").strip()
    if not pmcid:
        return None
    pmcid = pmcid if pmcid.startswith("PMC") else f"PMC{pmcid}"
    sections: list[Section] = []
    abstract = _text(article.find(".//abstract"))
    if abstract:
        sections.append(Section(title="Abstract", text=abstract))
    for sec in body.findall("sec"):
        sections += _sections(sec)
    loose = [_text(p) for p in body.findall("p")]  # some articles put paragraphs directly in body
    if any(loose):
        sections.append(Section(title="Body", text=" ".join(p for p in loose if p)))
    year = article.find(".//pub-date/year")
    return Document(
        id=f"pmc:{pmcid}",
        source="pmc",
        title=_text(article.find(".//article-title")) or pmcid,
        url=f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",
        license=licence,
        topic=topic,
        published=year.text if year is not None else None,
        sections=[s for s in sections if s.text],
    )


def search(client: httpx.Client, query: str, years: str, retmax: int) -> list[str]:
    title_terms = " AND ".join(f"{word}[ti]" for word in query.split())
    # Veterinary and animal-model reviews are the wrong domain (e.g. equine asthma dosing)
    not_animal = " OR ".join(f"{w}[ti]" for w in NOT_HUMAN_TITLE_WORDS)
    term = (
        f"({title_terms}) AND review[pt] AND (cc by license[filter] OR cc0 license[filter]) "
        f"AND {years}[pdat] NOT ({not_animal})"
    )
    params: dict[str, str | int] = {
        "db": "pmc",
        "term": term,
        "retmode": "json",
        "retmax": retmax,
        "sort": "relevance",
        "tool": "clinscribe",
    }
    response = client.get(f"{EUTILS}/esearch.fcgi", params=params)
    response.raise_for_status()
    time.sleep(NCBI_PAUSE_S)
    return [str(i) for i in response.json()["esearchresult"]["idlist"]]


def fetch_articles(client: httpx.Client, ids: list[str], raw_dir: Path) -> dict[str, ET.Element]:
    """PMC numeric id -> <article> element, using the raw cache where possible."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    missing = [i for i in ids if not (raw_dir / f"PMC{i}.xml").exists()]
    for start in range(0, len(missing), 20):
        batch = missing[start : start + 20]
        response = client.get(
            f"{EUTILS}/efetch.fcgi",
            params={"db": "pmc", "id": ",".join(batch), "retmode": "xml", "tool": "clinscribe"},
        )
        response.raise_for_status()
        time.sleep(NCBI_PAUSE_S)
        root = safe_fromstring(response.content)
        for article in root.iter("article"):
            for article_id in article.iter("article-id"):
                if article_id.get("pub-id-type") in ("pmc", "pmcid"):
                    number = (article_id.text or "").removeprefix("PMC").strip()
                    (raw_dir / f"PMC{number}.xml").write_bytes(ET.tostring(article))
    articles = {}
    for i in ids:
        path = raw_dir / f"PMC{i}.xml"
        if path.exists():
            articles[i] = safe_fromstring(path.read_bytes())
    return articles
