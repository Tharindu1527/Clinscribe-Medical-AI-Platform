"""Late chunking: windowing, chunk-to-token spans and window choice (no model needed)."""

import pytest

from retrieval.late_chunking import (
    assign_windows,
    best_window,
    char_spans,
    chunk_token_spans,
    section_chunks,
    windows,
)


def test_windows_cover_long_sections_with_overlap() -> None:
    assert windows(300, 512, 128) == [(0, 300)]  # short section: one window
    wins = windows(1000, 400, 100)
    assert wins == [(0, 400), (300, 700), (600, 1000)]
    assert all(b - a <= 400 for a, b in wins)
    with pytest.raises(ValueError, match="overlap"):
        windows(1000, 100, 100)


def test_char_spans_follow_overlapping_chunks_in_order() -> None:
    text = "Alpha beta. Gamma delta. Alpha beta. Epsilon."
    chunks = [{"id": "a", "text": "Alpha beta. Gamma delta."},
              {"id": "b", "text": "Gamma delta. Alpha beta."},
              {"id": "c", "text": "Alpha beta. Epsilon."}]  # fmt: skip
    # the third chunk's "Alpha beta." is the second occurrence, found after the previous start
    assert char_spans(text, chunks) == [(0, 24), (12, 36), (25, 45)]
    with pytest.raises(ValueError, match="not a substring"):
        char_spans(text, [{"id": "x", "text": "Zeta"}])


def test_chunk_token_spans_use_character_offsets() -> None:
    # tokens: "Alp"(0-3) "ha"(3-5) " beta"(5-10) "."(10-11) " Gamma"(11-17)
    offsets = [(0, 3), (3, 5), (5, 10), (10, 11), (11, 17)]
    assert chunk_token_spans(offsets, [(0, 11), (5, 17)]) == [(0, 4), (2, 5)]
    with pytest.raises(ValueError, match="no tokens"):
        chunk_token_spans(offsets, [(40, 50)])


def test_best_window_prefers_the_most_central_containing_window() -> None:
    wins = [(0, 400), (300, 700), (600, 1000)]
    assert best_window((340, 380), wins) == 1  # in 0 and 1; margins 20 vs 40 -> window 1
    assert best_window((650, 690), wins) == 2  # in 1 and 2; min margin 10 vs 50 -> window 2
    assert best_window((900, 950), wins) == 2
    with pytest.raises(ValueError, match="overlap_tokens"):
        best_window((350, 650), [(0, 400), (500, 900)])


def test_section_chunks_group_by_document_and_section() -> None:
    chunks = [{"id": "d:1#s0#c0", "doc_id": "d:1"}, {"id": "d:1#s0#c1", "doc_id": "d:1"},
              {"id": "d:1#s2#c0", "doc_id": "d:1"}]  # fmt: skip
    grouped = section_chunks(chunks)
    assert list(grouped) == [("d:1", 0), ("d:1", 2)]
    assert [c["id"] for c in grouped[("d:1", 0)]] == ["d:1#s0#c0", "d:1#s0#c1"]


def test_a_chunk_longer_than_the_overlap_gets_its_own_centred_window() -> None:
    wins = windows(1000, 400, 100)  # (0,400) (300,700) (600,1000)
    spans = [(10, 50), (250, 450)]  # the second crosses both overlaps: no standard window fits
    out, assignment = assign_windows(spans, wins, 400, 1000)
    assert assignment[0] == 0
    assert out[assignment[1]] == (150, 550)  # a new 400-token window centred on 250-450
    near_end, [index] = assign_windows([(700, 990)], [(0, 400), (300, 700)], 400, 1000)
    assert near_end[index] == (600, 1000)  # clipped at the end of the section
    with pytest.raises(ValueError, match="exceeds the window size"):
        assign_windows([(0, 500)], [(0, 400)], 400, 1000)
