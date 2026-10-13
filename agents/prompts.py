"""Versioned prompts (prompts/*.yaml). Only `user` is a format template; `system` is used as is,
so JSON examples in it need no brace escaping."""

from pathlib import Path

import yaml
from pydantic import BaseModel

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


class Prompt(BaseModel):
    id: str
    version: str
    task: str
    temperature: float
    max_tokens: int
    system: str
    user: str

    @property
    def ref(self) -> str:
        """Written into traces and audit records, e.g. "note_writer@v1"."""
        return f"{self.id}@v{self.version}"


def load(name: str) -> Prompt:
    data = yaml.safe_load((PROMPTS / f"{name}.yaml").read_text(encoding="utf-8"))
    return Prompt.model_validate({k: data[k] for k in Prompt.model_fields})
