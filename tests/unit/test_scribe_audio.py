"""Scribe from audio (voice/scribe.py, evals/voice/scribe_eval.py): turns, roles, scoring."""

import wave
from pathlib import Path

import numpy as np
import pytest

from evals.voice.scribe_eval import intervals, reference_role, score
from voice.scribe import (
    MAX_TURN_CHARS,
    Word,
    assign_roles,
    group_turns,
    read_wav,
    split_text,
    transcript_for_api,
    words_from_result,
)

pytestmark = pytest.mark.unit


def _result(words: list[dict[str, object]], final: bool = True) -> dict[str, object]:
    return {"type": "Results", "is_final": final, "channel": {"alternatives": [{"words": words}]}}


def test_final_results_give_punctuated_words_with_speakers() -> None:
    data = _result(
        [
            {"word": "hello", "punctuated_word": "Hello,", "start": 0.1, "end": 0.4, "speaker": 0},
            {"word": "doctor", "start": 0.5, "end": 0.9, "speaker": 1},
        ]
    )
    assert words_from_result(data) == [
        Word("Hello,", 0.1, 0.4, 0),
        Word("doctor", 0.5, 0.9, 1),
    ]
    assert words_from_result(_result([{"word": "x", "start": 0, "end": 1}], final=False)) == []
    assert words_from_result({"type": "Metadata"}) == []


def test_consecutive_words_of_one_speaker_form_a_turn() -> None:
    words = [
        Word("Thirsty", 2.0, 2.4, 1),
        Word("How", 0.0, 0.2, 0),
        Word("are", 0.3, 0.4, 0),
        Word("you?", 0.5, 0.8, 0),
        Word("Since?", 3.0, 3.4, 0),
    ]
    turns = group_turns(words)
    assert [(t.speaker, t.text) for t in turns] == [
        (0, "How are you?"),
        (1, "Thirsty"),
        (0, "Since?"),
    ]
    assert (turns[0].start, turns[0].end) == (0.0, 0.8)


def test_first_full_sentence_speaker_is_the_doctor_others_are_the_patient_side() -> None:
    turns = group_turns(
        [
            Word("Hi.", 0.0, 0.2, 1),  # a short greeting does not decide the roles
            Word("Good", 0.5, 0.7, 0),
            Word("morning,", 0.7, 0.9, 0),
            Word("what", 1.0, 1.1, 0),
            Word("brings", 1.1, 1.3, 0),
            Word("Me", 2.0, 2.1, 2),  # a companion
        ]
    )
    assert assign_roles(turns) == {0: "doctor", 1: "patient", 2: "patient"}
    assert assign_roles([]) == {}


def test_a_small_diarization_fragment_is_unknown_and_does_not_decide_the_doctor() -> None:
    fragment = [Word(w, i * 0.1, i * 0.1 + 0.05, 0) for i, w in enumerate(["Hello?", "Hi.", "Um,"])]
    doctor = [Word("word", 1 + i * 0.1, 1 + i * 0.1 + 0.05, 1) for i in range(60)]
    patient = [Word("word", 8 + i * 0.1, 8 + i * 0.1 + 0.05, 2) for i in range(40)]
    turns = group_turns(fragment + doctor + patient)
    assert assign_roles(turns) == {0: "unknown", 1: "doctor", 2: "patient"}
    assert assign_roles(turns, min_share=0.0) == {0: "doctor", 1: "patient", 2: "patient"}


def test_long_turns_are_split_under_the_api_limit_without_losing_words() -> None:
    text = " ".join(["The patient describes the pain in detail."] * 200)
    parts = split_text(text)
    assert len(parts) > 1
    assert all(len(p) <= MAX_TURN_CHARS for p in parts)
    assert " ".join(parts).split() == text.split()
    assert split_text("short") == ["short"]
    turns = group_turns([Word("Hello", 0, 1, 0), Word("Hi", 1, 2, 1)])
    assert transcript_for_api(turns, {0: "doctor", 1: "patient"}) == [
        {"speaker": "doctor", "text": "Hello"},
        {"speaker": "patient", "text": "Hi"},
    ]


def test_stereo_wav_is_mixed_to_mono_and_other_rates_are_refused(tmp_path: Path) -> None:
    stereo = tmp_path / "stereo.wav"
    with wave.open(str(stereo), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(16_000)
        out.writeframes(np.array([100, 300, -200, 0], dtype="<i2").tobytes())
    assert np.frombuffer(read_wav(stereo), dtype="<i2").tolist() == [200, -100]
    slow = tmp_path / "slow.wav"
    with wave.open(str(slow), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8_000)
        out.writeframes(bytes(4))
    with pytest.raises(SystemExit):
        read_wav(slow)


GRID = """
        intervals [1]:
            xmin = 0
            xmax = 1.5
            text = ""
        intervals [2]:
            xmin = 1.5
            xmax = 4.0
            text = "Good morning, how can I help?"
"""


def test_textgrid_intervals_and_reference_roles() -> None:
    doctor = intervals(GRID)
    assert doctor == [(1.5, 4.0, "Good morning, how can I help?")]
    patient = [(3.5, 6.0, "I feel tired")]
    assert reference_role(2.0, doctor, patient) == "doctor"
    assert reference_role(5.0, doctor, patient) == "patient"
    assert reference_role(3.8, doctor, patient) is None  # overlap
    assert reference_role(0.5, doctor, patient) is None  # silence


def test_score_on_a_hand_worked_consultation() -> None:
    doctor = [(0.0, 2.0, "good morning how can i help")]
    patient = [(2.5, 4.0, "i feel tired")]
    words = [
        Word("Good", 0.1, 0.3, 0),
        Word("morning,", 0.3, 0.6, 0),
        Word("how", 0.7, 0.9, 0),
        Word("can", 1.0, 1.2, 0),
        Word("I", 1.2, 1.3, 0),
        Word("help?", 1.3, 1.6, 0),
        Word("I", 2.6, 2.8, 1),
        Word("feel", 2.9, 3.2, 0),  # misattributed to the doctor's speaker
        Word("tired.", 3.3, 3.8, 1),
    ]
    out = score(words, doctor, patient)
    assert out["scored"] == 9
    assert out["attribution"] == out["attribution_v1"] == pytest.approx(8 / 9)
    assert out["purity"] == pytest.approx(8 / 9)
    assert out["rule_ok"] is True
    assert out["wer"] == 0.0
    assert (out["turns"], out["reference_turns"]) == (4, 2)
