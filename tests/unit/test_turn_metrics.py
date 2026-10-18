"""Turn-taking scoring (voice/turn_metrics.py) on hand-worked timelines."""

import math

import pytest

from voice.turn_metrics import Utterance, classify, percentile, stop_latency

pytestmark = pytest.mark.unit


def test_a_commit_inside_the_pause_is_a_cut_off() -> None:
    paused = Utterance("What is the dose of ... metformin?", 10.0, 14.0, pause=(11.5, 12.7))
    out = classify(paused, commits=[12.4, 14.6], window_end=19.0)
    assert out == {"cut_off": True, "delay": pytest.approx(0.6), "missed": False, "commits": 2}


def test_a_commit_just_after_speech_resumes_still_counts_as_the_cut_off() -> None:
    # the transcript for the first half can arrive shortly after the speaker carries on
    paused = Utterance("q", 10.0, 14.0, pause=(11.5, 12.7))
    assert classify(paused, commits=[13.1, 14.8], window_end=19.0)["cut_off"] is True
    assert classify(paused, commits=[13.3, 14.8], window_end=19.0)["cut_off"] is False


def test_whole_utterance_delay_and_missed_turns() -> None:
    whole = Utterance("q", 0.0, 3.0)
    assert classify(whole, commits=[3.8, 20.0], window_end=8.0) == {
        "cut_off": False,
        "delay": pytest.approx(0.8),
        "missed": False,
        "commits": 1,
    }
    assert classify(whole, commits=[9.0], window_end=8.0)["missed"] is True


def test_percentiles_and_stop_latency() -> None:
    assert percentile([0.4, 0.1, 0.3, 0.2], 50) == 0.2
    assert percentile([0.4, 0.1, 0.3, 0.2], 95) == 0.4
    assert math.isnan(percentile([], 50))
    assert stop_latency(5.0, cleared=[2.0, 5.62, 9.0]) == pytest.approx(0.62)
    assert stop_latency(5.0, cleared=[2.0, 11.0]) is None
