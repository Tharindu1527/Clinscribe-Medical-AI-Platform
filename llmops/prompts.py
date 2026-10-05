"""Load versioned prompts from prompts/*.yaml (SPEC section 7: prompts and configs as code)."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from privacy.deid.types import DeidentifiedText, issue

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    task: str
    temperature: float
    max_tokens: int
    system: DeidentifiedText  # template text written by us: contains no PHI by construction

    @property
    def tag(self) -> str:
        return f"{self.id}@v{self.version}"


def load_prompt(prompt_id: str, directory: Path = PROMPTS_DIR) -> Prompt:
    data = yaml.safe_load((directory / f"{prompt_id}.yaml").read_text(encoding="utf-8"))
    if data["id"] != prompt_id:
        raise ValueError(f"{prompt_id}.yaml declares id {data['id']!r}")
    return Prompt(
        id=data["id"],
        version=str(data["version"]),
        task=data["task"],
        temperature=float(data["temperature"]),
        max_tokens=int(data["max_tokens"]),
        system=issue(
            data["system"].strip(), source=f"prompt-template:{prompt_id}@v{data['version']}"
        ),
    )
