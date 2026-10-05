"""The type that marks text as de-identified (CLAUDE.md: no PHI reaches an LLM before privacy/deid).

`DeidentifiedText` can only be created through `issue()`, which the de-ID service calls after
scrubbing text (task 6). The gateway client accepts nothing else, so a plain `str` cannot reach
a model by accident: the type checker rejects it and the client re-checks at runtime.
"""

from dataclasses import dataclass, field

_ISSUER = object()  # private capability: only code holding it can mint DeidentifiedText


@dataclass(frozen=True)
class DeidentifiedText:
    text: str
    source: str  # who vouched for it, e.g. "deid-service" or "synthetic-test-fixture"
    _issuer: object = field(repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self._issuer is not _ISSUER:
            raise TypeError("DeidentifiedText must be created by privacy.deid.types.issue()")


def issue(text: str, source: str) -> DeidentifiedText:
    """Mint a DeidentifiedText. Call only after de-identification, or for fixed synthetic test
    text that contains no PHI by construction (source="synthetic-test-fixture")."""
    return DeidentifiedText(text=text, source=source, _issuer=_ISSUER)
