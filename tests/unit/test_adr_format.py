"""ADRs follow the format in CLAUDE.md: context, options, decision, consequences."""

import re
from pathlib import Path

import pytest

ADR_DIR = Path(__file__).resolve().parents[2] / "docs" / "adr"
ADRS = sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))
REQUIRED_HEADINGS = ["## Context", "## Options", "## Decision", "## Consequences"]


def test_adrs_exist_and_are_numbered_without_gaps() -> None:
    numbers = [int(path.name[:4]) for path in ADRS]
    assert numbers, "no ADRs found"
    assert numbers == list(range(1, len(numbers) + 1))


@pytest.mark.parametrize("path", ADRS, ids=lambda p: p.name)
def test_adr_has_title_status_and_required_sections(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.startswith(f"# ADR-{path.name[:4]}: ")
    assert re.search(r"^Status: (Proposed|Accepted|Superseded by ADR-\d{4}|Deprecated)", text, re.M)
    positions = [text.find(heading) for heading in REQUIRED_HEADINGS]
    assert all(pos >= 0 for pos in positions), f"missing one of {REQUIRED_HEADINGS}"
    assert positions == sorted(positions), "sections out of order"
