"""Doctors' edits as evaluation data (SPEC section 5: "Doctor edits are saved as before/after pairs,
which become new evaluation data"; ADR-0028).

Reads the pairs the API keeps when a doctor approves an edited draft (`edit_pairs`, surrogate form)
and writes the ones that pass a PHI scan to data/edit_pairs/edit_pairs.jsonl (git-ignored), with
what changed per statement: unchanged, edited, removed or added (aligned in order, by section and
text). The scan runs every statement of both sides through the de-ID engine with the spaCy rules
(in memory, nothing stored): a pair where it would replace anything is withheld, since a doctor's
wording can carry PHI the first pass missed (ADR-0015), and the AI side was never de-identified
(it is model output from surrogate input). The spaCy rules, not the service's recogniser: the same
engine finds nothing new in text it de-identified, and the fine-tuned tagger (ADR-0014) took
"Patient" at the start of a sentence for a name, which withheld the first real pair. Prints counts
only; the rows stay on this machine.

  uv run python -m evals.agents.edit_pairs        (needs `just up`; reads as the app login)
"""

import difflib
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from apps.api.edits import EditPair, PostgresEditPairs
from config.db import app_conninfo
from config.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "edit_pairs" / "edit_pairs.jsonl"
KINDS = ("unchanged", "edited", "removed", "added")


class Deidentifies(Protocol):
    def deidentify(self, text: str, encounter_id: str) -> Any: ...


def changes(
    before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]]
) -> Counter[str]:
    """Statements unchanged, edited (same place, new text), removed and added, by alignment of the
    (section, text) sequences; counted overall and per section ("edited:plan")."""
    a = [(s["section"], s["text"]) for s in before]
    b = [(s["section"], s["text"]) for s in after]
    out: Counter[str] = Counter()

    def count(kind: str, statements: Sequence[tuple[str, str]]) -> None:
        for section, _ in statements:
            out[kind] += 1
            out[f"{kind}:{section}"] += 1

    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            count("unchanged", a[i1:i2])
        elif op == "delete":
            count("removed", a[i1:i2])
        elif op == "insert":
            count("added", b[j1:j2])
        else:  # replace: pairwise edits, then the rest removed or added
            paired = min(i2 - i1, j2 - j1)
            count("edited", b[j1 : j1 + paired])
            count("removed", a[i1 + paired : i2])
            count("added", b[j1 + paired : j2])
    return out


def phi_found(pair: EditPair, deidentifier: Deidentifies) -> int:
    """Statements of either side in which the de-ID engine would still replace something."""
    texts = [s["text"] for note in (pair.before, pair.after) for s in note.get("statements", [])]
    return sum(bool(deidentifier.deidentify(t, "edit-pair-scan").replacements) for t in texts)


def export(
    pairs: Sequence[EditPair], deidentifier: Deidentifies
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()
    withheld = 0
    for pair in pairs:
        if phi_found(pair, deidentifier):
            withheld += 1
            continue
        changed = changes(pair.before["statements"], pair.after["statements"])
        totals.update(changed)
        rows.append(
            {
                "draft_id": pair.draft_id,
                "prompt_version": pair.prompt_version,
                "model": pair.model,
                "before": pair.before["statements"],
                "after": pair.after["statements"],
                "changes": {k: changed[k] for k in KINDS},
            }
        )
    summary = {
        "pairs": len(pairs),
        "withheld_phi": withheld,
        "exported": len(rows),
        **{k: totals[k] for k in KINDS},
        "by_section": {k: v for k, v in sorted(totals.items()) if ":" in k},
        "by_prompt": dict(Counter(r["prompt_version"] for r in rows)),
    }
    return rows, summary


def main() -> int:
    from evals.privacy.deid_eval import deidentifier_for  # loads spaCy: only when exporting

    settings = Settings()
    deidentifier = deidentifier_for("spacy", settings.deid_spacy_model)
    rows, summary = export(PostgresEditPairs(app_conninfo(settings)).all(), deidentifier)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "".join(json.dumps(r, default=str) + "\n" for r in rows), encoding="utf-8", newline="\n"
    )
    print(json.dumps(summary, indent=2))
    withheld = summary["withheld_phi"]
    print(f"wrote {len(rows)} pairs to {OUT} (git-ignored; withheld for PHI: {withheld})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
