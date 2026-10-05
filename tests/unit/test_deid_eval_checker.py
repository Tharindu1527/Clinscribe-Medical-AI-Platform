"""The leak checker used by the privacy eval must neither miss leaks nor invent them."""

import pytest

from evals.privacy.deid_eval import leaked


@pytest.mark.parametrize(
    ("entity", "value", "output", "expected"),
    [
        # Digits inside a surrogate label are not a leak ("AGE_OVER_89_1" contains "91")
        ("AGE_OVER_89", "91", "A AGE_OVER_89_1-year-old woman.", False),
        ("PHONE", "(617) 555-0142", "Call PHONE_1.", False),
        # Real leaks, including reformatted ones
        ("PHONE", "(617) 555-0142", "Call 617.555.0142.", True),
        ("AGE_OVER_89", "91", "A 91-year-old woman.", True),
        # Names leak if any part survives as a whole word
        ("PERSON", "Ada Lovelace", "Seen by PERSON_1 Lovelace.", True),
        ("PERSON", "Ada Lovelace", "Seen by PERSON_1.", False),
    ],
)
def test_leak_checker(entity: str, value: str, output: str, expected: bool) -> None:
    assert leaked(entity, value, output) is expected
