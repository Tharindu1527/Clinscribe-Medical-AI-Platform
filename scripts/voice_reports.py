"""Phase 4 gate: the voice reports exist and contain what SPEC section 12 asks for.

uv run python -m scripts.voice_reports latency|asr
"""

import sys
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[1] / "evals" / "reports" / "voice"
REQUIRED = {
    "latency": ("latency.md", ("**TTFA**", "Turn time", "## Bottleneck")),
    "asr": ("asr_wer.md", ("nova-3-medical", "keyterms", "medical-term")),
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in REQUIRED:
        print(f"usage: voice_reports {'|'.join(REQUIRED)}")
        return 2
    name, needles = REQUIRED[argv[0]]
    path = REPORTS / name
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [n for n in needles if n not in text]
    print(f"{path.name}: " + ("ok" if not missing else f"missing {missing}"))
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
