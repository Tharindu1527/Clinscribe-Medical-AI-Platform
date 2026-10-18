"""Scoring for the turn-taking eval (voice/turn_eval.py); no LiveKit imports, so it is unit-tested
in the main project. Times are seconds on the simulated sound card's clock."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Utterance:
    text: str
    start: float  # first speech sample
    end: float  # last speech sample
    pause: tuple[float, float] | None = None  # the silence inside the sentence, if any


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile; nan for no values."""
    if not values:
        return math.nan
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


def classify(utterance: Utterance, commits: list[float], window_end: float) -> dict[str, object]:
    """What the turn detector did with one utterance, from the times user turns were committed.

    - cut_off: a commit inside the mid-sentence pause (up to 0.5 s after speech resumed, for the
      transcript to arrive): the doctor's turn was ended while they were still speaking;
    - delay: first commit after the utterance ended, minus its end (the end-of-turn delay);
    - missed: no commit for the utterance before `window_end`.
    """
    mine = [c for c in commits if utterance.start < c <= window_end]
    cut = False
    if utterance.pause is not None:
        pause_start, pause_end = utterance.pause
        cut = any(pause_start < c <= pause_end + 0.5 for c in mine)
    after = [c - utterance.end for c in mine if c > utterance.end]
    return {
        "cut_off": cut,
        "delay": min(after) if after else None,
        "missed": not mine,
        "commits": len(mine),
    }


def stop_latency(onset: float, cleared: list[float], within: float = 5.0) -> float | None:
    """Seconds from the user's speech onset to the agent's audio being cleared (barge-in)."""
    after = [c - onset for c in cleared if 0 <= c - onset <= within]
    return min(after) if after else None
