"""Guardrails on agent inputs and outputs (SPEC section 5; Phase 3 task 7).

Rules live in config/guardrails.yaml.

Input
- `check_deidentified`: text bound for a model carries no structured PHI (dates, phones, IDs, ...);
  the de-ID service ran before, this is the second check (CLAUDE.md).
- `screen_evidence`: passages with prompt-injection text are dropped, and reported.
Output
- every cited id was actually given to the model (no invented sources);
- a dose (number + unit) is only stated when a cited source contains the same number and unit;
- no definitive diagnosis or individual treatment decision;
- note statements point at transcript turns that exist.
The graph retries once with the violations attached, then returns the safe reply (agents/graph.py).
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agents.schemas import AskAnswer, Evidence, SoapNote
from llmops.telemetry.redaction import scrub

CONFIG = Path(__file__).resolve().parents[1] / "config" / "guardrails.yaml"


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.detail}"


class Guardrails:
    def __init__(self, path: Path = CONFIG) -> None:
        cfg: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.version = str(cfg["version"])
        flags = re.IGNORECASE
        self._injection = [re.compile(p, flags) for p in cfg["input"]["injection_patterns"]]
        self._dose = re.compile(cfg["output"]["dose_pattern"], flags)
        self._diagnosis = [re.compile(p, flags) for p in cfg["output"]["diagnosis_patterns"]]
        self.safe_reply = str(cfg["output"]["safe_reply"])
        self.max_attempts = int(cfg["output"]["max_attempts"])

    # ---------------------------------------------------------------- input
    def check_deidentified(self, text: str) -> list[Violation]:
        return [Violation("phi_in_input", "structured PHI found")] if scrub(text) != text else []

    def injection(self, text: str) -> str | None:
        for pattern in self._injection:
            match = pattern.search(text)
            if match:
                return match.group(0)
        return None

    def screen_evidence(
        self, evidence: Sequence[Evidence]
    ) -> tuple[list[Evidence], list[Violation]]:
        kept, dropped = [], []
        for item in evidence:
            found = self.injection(item.text)
            if found:
                dropped.append(Violation("injection_in_evidence", f"{item.chunk_id}: {found!r}"))
            else:
                kept.append(item)
        return kept, dropped

    # ---------------------------------------------------------------- output
    def doses(self, text: str) -> set[tuple[str, str]]:
        """(number, unit) pairs; units normalised so "5 milligrams"/"5 mg" style variants match."""
        out = set()
        text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 1,000 units -> 1000 units
        for match in self._dose.finditer(text):
            unit = match.group(2).lower().rstrip("s")
            unit = {"microgram": "mcg", "µg": "mcg", "gram": "g", "iu": "unit"}.get(unit, unit)
            for number in re.findall(r"\d+(?:[.,]\d+)?", match.group(0)):  # both ends of 2-5 mg
                out.add((number.replace(",", "."), unit))
        return out

    def _sentence_checks(
        self, label: str, text: str, cited: Iterable[str], sources: Mapping[str, str]
    ) -> list[Violation]:
        cited = list(cited)
        found = []
        unknown = [c for c in cited if c not in sources]
        if unknown:
            found.append(Violation("unknown_citation", f"{label} cites {unknown}"))
        doses = self.doses(text)
        if doses:
            supported = set().union(*(self.doses(sources[c]) for c in cited if c in sources))
            missing = sorted(doses - supported)
            if missing:
                found.append(
                    Violation("unsourced_dose", f"{label} states {missing} not in its sources")
                )
        for pattern in self._diagnosis:
            match = pattern.search(text)
            if match:
                found.append(Violation("diagnosis_wording", f"{label}: {match.group(0)!r}"))
                break
        return found

    def check_answer(self, answer: AskAnswer, sources: Mapping[str, str]) -> list[Violation]:
        """`sources`: chunk id -> text of every passage the model was given."""
        found: list[Violation] = []
        for n, sentence in enumerate(answer.sentences, start=1):
            found += self._sentence_checks(
                f"sentence {n}", sentence.text, sentence.citations, sources
            )
        return found

    def check_note(
        self, note: SoapNote, transcript: Sequence[str], sources: Mapping[str, str]
    ) -> list[Violation]:
        """A dose in a note may come from the transcript (what was said) or from a cited source."""
        found: list[Violation] = []
        for n, statement in enumerate(note.statements, start=1):
            label = f"statement {n} ({statement.section})"
            bad_turns = [t for t in statement.transcript_turns if not 0 <= t < len(transcript)]
            if bad_turns:
                found.append(Violation("unknown_turn", f"{label} points at turns {bad_turns}"))
            spoken = {
                d
                for t in statement.transcript_turns
                if 0 <= t < len(transcript)
                for d in self.doses(transcript[t])
            }
            checks = self._sentence_checks(label, statement.text, statement.citations, sources)
            for violation in checks:
                if violation.rule == "unsourced_dose" and self.doses(statement.text) <= (
                    spoken
                    | set().union(*(self.doses(sources.get(c, "")) for c in statement.citations))
                ):
                    continue  # the dose was said in the consultation
                found.append(violation)
        return found
