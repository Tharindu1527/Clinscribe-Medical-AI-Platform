"""The fine-tuned name/place tagger as a de-ID recogniser (ADR-0014)."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from privacy.deid.engine import Deidentifier, analyzer_for
from privacy.deid.store import InMemoryStore
from privacy.deid.tagger import bio_spans, trim_full_stop

pytestmark = pytest.mark.unit
MODEL = Path(__file__).resolve().parents[2] / "data" / "finetune" / "deid_ner_tagger"


def test_bio_tags_become_character_spans() -> None:
    #           Ada      Lovelace   lives    in       London    .
    words = [(0, 3), (4, 12), (13, 18), (19, 21), (22, 28), (28, 29)]
    tags = ["B-PERSON", "I-PERSON", "O", "O", "B-LOCATION", "O"]
    assert bio_spans(words, tags) == [("PERSON", 0, 12), ("LOCATION", 22, 28)]


def test_a_stray_inside_tag_starts_a_new_entity_and_the_last_entity_is_closed() -> None:
    words = [(0, 2), (3, 5), (6, 8)]
    assert bio_spans(words, ["I-PERSON", "B-LOCATION", "I-LOCATION"]) == [
        ("PERSON", 0, 2),
        ("LOCATION", 3, 8),
    ]
    assert bio_spans(words, ["O", "O", "O"]) == []
    assert bio_spans(words, ["B-PERSON", "I-LOCATION", "O"]) == [
        ("PERSON", 0, 2),
        ("LOCATION", 3, 5),
    ]


def test_a_span_does_not_take_the_sentence_full_stop_but_an_initial_keeps_its_dot() -> None:
    text = "Trip to Denver. Seen by J. Smith A."
    assert text[8 : trim_full_stop(text, 8, 15)] == "Denver"
    assert text[24 : trim_full_stop(text, 24, 26)] == "J."  # too short to be a sentence end
    assert text[24 : trim_full_stop(text, 24, 35)] == "J. Smith A."  # ends in an initial


class _Encoded(dict[str, list[int]]):
    def __init__(self, label_ids: list[int], word_ids: list[int | None]) -> None:
        super().__init__(input_ids=label_ids)
        self._word_ids = word_ids

    def word_ids(self, batch: int) -> list[int | None]:
        return self._word_ids


class _TwoTokensPerWord:
    """Each word is two sub-words; the window is cut at max_length like a real tokenizer."""

    def __call__(self, words: list[str], *, max_length: int, **_: object) -> _Encoded:
        fit = min(len(words), (max_length - 2) // 2)
        word_ids: list[int | None] = [None]
        labels = [0]
        for i in range(fit):
            word_ids += [i, i]
            labels += [1, 2] if words[i][0].isupper() else [0, 0]  # B-PERSON on a capital
        return _Encoded([*labels, 0], [*word_ids, None])


class _EchoModel:
    """The 'logits' argmax is the label the fake tokenizer put in input_ids."""

    def __call__(self, input_ids: list[int]) -> object:
        class Logits:
            def __getitem__(self, _: int) -> "Logits":
                return self

            def argmax(self, _: int) -> "Logits":
                return self

            def tolist(self) -> list[int]:
                return input_ids

        return type("Out", (), {"logits": Logits()})()


def test_a_window_cut_by_the_token_limit_goes_on_from_the_first_word_left_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import contextlib
    import types

    from privacy.deid import tagger

    monkeypatch.setattr(tagger, "MAX_TOKENS", 12)  # 5 words per call, though WINDOW is 200
    recognizer = tagger.TaggerRecognizer.__new__(tagger.TaggerRecognizer)
    recognizer._tok = _TwoTokensPerWord()
    recognizer._model = _EchoModel()
    recognizer._torch = types.SimpleNamespace(no_grad=contextlib.nullcontext)
    words = ["w"] * 12 + ["Ellis"] + ["w"] * 4
    tags = recognizer.tags(words)
    assert len(tags) == len(words)
    assert [i for i, tag in enumerate(tags) if tag != "O"] == [12]
    assert tags[12] == "B-PERSON"


def test_unknown_recogniser_choice_is_refused() -> None:
    with pytest.raises(ValueError, match="DEID_NER"):
        analyzer_for("bert", "en_core_web_md")


@pytest.mark.skipif(not MODEL.exists(), reason="merged tagger not built (finetune/merge.py)")
def test_the_tagger_redacts_names_and_places_and_keeps_clinical_words() -> None:
    store = InMemoryStore(SecretStr(Fernet.generate_key().decode()))
    deid = Deidentifier(analyzer_for("tagger", "en_core_web_md", str(MODEL)), store)
    out = deid.deidentify("Spoke to Morgan Ellis about her trip to Denver.", "enc-tag").text.text
    for secret in ("Morgan", "Ellis", "Denver"):
        assert secret not in out, out
    assert out.endswith("."), out  # the full stop after the place stays
    kept = "Lungs clear to auscultation; started Ventolin 100 mcg on Ward 4."
    assert deid.deidentify(kept, "enc-tag").text.text == kept
