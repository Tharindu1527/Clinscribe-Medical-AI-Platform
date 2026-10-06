"""Corpus ingestion: parsing, licence filtering, chunking and de-duplication on small fixtures."""

from defusedxml.ElementTree import fromstring

from retrieval.ingest.chunking import chunk_document
from retrieval.ingest.models import Document, Section, garbled_share
from retrieval.ingest.pipeline import dedupe_chunks, dedupe_documents
from retrieval.ingest.sources.openfda import matches_generic, parse_label
from retrieval.ingest.sources.pmc import licence_of, parse_article
from retrieval.ingest.sources.who import (
    page_text,
    repair_text,
    sections_from_outline,
    strip_running_lines,
)


def _jats(
    licence_href: str,
    body: str = "<sec><title>Treatment</title><p>Start an ACE inhibitor.</p></sec>",
) -> str:
    return f"""<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>
      <article-id pub-id-type="pmc">12345</article-id>
      <title-group><article-title>Managing hypertension</article-title></title-group>
      <pub-date><year>2024</year></pub-date>
      <permissions><license xlink:href="{licence_href}"><p>Licence text.</p></license></permissions>
      <abstract><p>A short abstract.</p></abstract>
    </article-meta></front><body>{body}</body></article>"""


def test_pmc_keeps_cc_by_and_parses_sections() -> None:
    xml = _jats(
        "https://creativecommons.org/licenses/by/4.0/",
        "<sec><title>Treatment</title><p>Start an ACE inhibitor.</p>"
        "<sec><title>Follow-up</title><p>Review in 4 weeks.</p></sec></sec>"
        "<sec><title>References</title><p>[1] Someone.</p></sec>",
    )
    doc = parse_article(fromstring(xml), topic="hypertension management")
    assert doc is not None
    assert (doc.id, doc.license, doc.published) == ("pmc:PMC12345", "CC BY 4.0", "2024")
    assert doc.url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/"
    assert [s.title for s in doc.sections] == ["Abstract", "Treatment", "Treatment > Follow-up"]


def test_pmc_accepts_cc0_and_rejects_non_commercial_and_abstract_only() -> None:
    assert (
        licence_of(fromstring(_jats("https://creativecommons.org/publicdomain/zero/1.0/")))
        == "CC0 1.0"
    )
    assert (
        parse_article(fromstring(_jats("https://creativecommons.org/licenses/by-nc/4.0/")), "t")
        is None
    )
    no_body = _jats("https://creativecommons.org/licenses/by/4.0/").replace(
        "<body><sec><title>Treatment</title><p>Start an ACE inhibitor.</p></sec></body>", ""
    )
    assert parse_article(fromstring(no_body), "t") is None


def test_openfda_label_keeps_configured_sections_and_dailymed_link() -> None:
    label = {
        "set_id": "abc-123",
        "effective_time": "20250101",
        "openfda": {"brand_name": ["Coumadin"]},
        "indications_and_usage": ["Prophylaxis of venous thrombosis."],
        "drug_interactions": ["Many drugs  interact\nwith warfarin."],
        "spl_unclassified_section": ["ignored"],
    }
    doc = parse_label(
        label, "warfarin", ["indications_and_usage", "drug_interactions"], "drug label"
    )
    assert doc.id == "fda:abc-123"
    assert doc.url.endswith("setid=abc-123")
    assert [s.title for s in doc.sections] == ["Indications and usage", "Drug interactions"]
    assert doc.sections[1].text == "Many drugs interact with warfarin."


def test_who_outline_sections_cover_page_ranges_and_skip_front_matter() -> None:
    pages = ["Contents page", "Intro text.", "Treatment text one.", "Treatment text two.", "Refs."]
    outline = [("Contents", 0), ("Introduction", 1), ("Treatment", 2), ("References", 4)]
    sections = sections_from_outline(outline, pages)
    assert [(s.title, s.text) for s in sections] == [
        ("Introduction", "Intro text."),
        ("Treatment", "Treatment text one. Treatment text two."),
    ]
    assert [s.title for s in sections_from_outline([], ["a", "", "b"])] == ["Page 1", "Page 3"]


def test_openfda_picks_the_product_not_a_combination() -> None:
    single = {"openfda": {"generic_name": ["AMLODIPINE BESYLATE"]}}
    combo = {"openfda": {"generic_name": ["AMLODIPINE BESYLATE AND BENAZEPRIL HYDROCHLORIDE"]}}
    amox_clav = {"openfda": {"generic_name": ["AMOXICILLIN AND CLAVULANATE POTASSIUM"]}}
    assert matches_generic(single, "amlodipine")
    assert not matches_generic(combo, "amlodipine")
    assert matches_generic(amox_clav, "amoxicillin and clavulanate potassium")
    assert not matches_generic(amox_clav, "amoxicillin")


def test_running_headers_and_page_numbers_are_removed_but_repeated_content_kept() -> None:
    drugs = ["Amoxicillin", "Doxycycline", "Nitrofurantoin", "Cefalexin", "Azithromycin"] * 2
    advice = ["Give with food.", "Avoid in pregnancy.", "Check renal function.", "Use 5 days.",
              "Review at 48 hours."] * 2  # fmt: skip
    pages = [
        f"{n}The WHO AWaRe antibiotic book\n{drugs[n - 1]} is first choice.\n"
        f"Strength of recommendation: strong\n{advice[n - 1]}\n{n}"
        for n in range(1, 11)
    ]
    cleaned = strip_running_lines(pages)
    assert all("AWaRe" not in page for page in cleaned)  # running header removed
    assert cleaned[0] == (
        "Amoxicillin is first choice.\nStrength of recommendation: strong\nGive with food."
    )  # page number removed; varied edge content kept
    # repeats on every page but sits mid-page: real content, kept
    assert all("Strength of recommendation: strong" in page for page in cleaned)


def test_who_font_repairs_decode_offset_text_and_never_guess_unknown_glyphs() -> None:
    assert repair_text("if SHUVLVWHQW\x03%3\x03Ȳ\x03\x14\x17\x13 mmHg") == (
        "if persistent BP [?] 140 mmHg"  # unknown glyph stays unknown, not a guessed threshold
    )
    assert repair_text("(΍HFWLYH\x03WUHDWPHQW") == "Effective treatment"
    assert repair_text(":LWKLQ\x03ER[\x03ȴQG\x03LQGLYLGXDOȇV") == "Within box find individual's"
    assert repair_text("Moderate ") == "Moderate ⊕⊕⊕◯"
    assert repair_text(" To consider ") == "• To consider 2 3"
    assert repair_text("Normal TREAT COUNSEL text 140/90.") == "Normal TREAT COUNSEL text 140/90."


def test_page_text_keeps_offset_digit_nine_and_drops_header_marker_lines() -> None:
    # \x1c is the offset-encoded "9"; str.splitlines() would treat it as a line break
    raw = "Chapter 2 heading \nBP \x14\x17\x13\x12\x1c\x13\x03PP+J target"
    assert page_text(raw) == "BP 140/90 mmHg target"


def test_pmc_formulas_become_placeholders() -> None:
    xml = _jats(
        "https://creativecommons.org/licenses/by/4.0/",
        "<sec><title>Model</title><p>We propose that <inline-formula><tex-math>"
        "\\documentclass{minimal}\\usepackage{amsmath} x^2</tex-math></inline-formula>"
        " holds.</p></sec>",
    )
    doc = parse_article(fromstring(xml), "t")
    assert doc is not None
    assert doc.sections[-1].text == "We propose that [formula] holds."


def test_garbled_share_flags_broken_font_text() -> None:
    assert garbled_share("Metronidazole 7.5 mg/kg every 8 hours • ≥ 2 years") == 0.0
    assert garbled_share("'L΍HUHQWLDOGLDJQRVLV") > 0.02


def _doc(doc_id: str, *texts: str) -> Document:
    return Document(
        id=doc_id,
        source="pmc",
        title="T",
        url="https://example.org",
        license="CC BY 4.0",
        topic="t",
        sections=[Section(title=f"S{i}", text=t) for i, t in enumerate(texts)],
    )


def test_chunks_stay_inside_sections_overlap_and_have_stable_ids() -> None:
    long_text = " ".join(f"Sentence number {i} about blood pressure targets." for i in range(60))
    doc = _doc("pmc:PMC1", long_text, "Too short.")
    chunks = chunk_document(doc, target=60, overlap=15, min_words=5)
    assert all(c.section == "S0" for c in chunks)  # the 2-word section is below min_words
    assert [c.id for c in chunks][:2] == ["pmc:PMC1#s0#c0", "pmc:PMC1#s0#c1"]
    assert all(len(c.text.split()) <= 60 + 8 for c in chunks)
    first_words = set(chunks[0].text.split()[-10:])
    assert first_words & set(chunks[1].text.split()[:15])  # overlap carried over
    assert chunks == chunk_document(doc, target=60, overlap=15, min_words=5)  # deterministic


def test_duplicates_are_removed() -> None:
    docs = dedupe_documents(
        [_doc("pmc:PMC2", "Same text."), _doc("pmc:PMC1", "Same  TEXT."), _doc("pmc:PMC3")]
    )
    assert [d.id for d in docs] == ["pmc:PMC1"]  # same content kept once; empty doc dropped
    a, b = chunk_document(_doc("pmc:PMC9", "Alpha beta gamma delta epsilon."), 50, 5, 1) * 2
    assert dedupe_chunks([a, b]) == [a]
