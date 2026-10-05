"""PHI recognisers for the 18 HIPAA Safe Harbor identifier types (SPEC section 8).

Structured identifiers use explicit regexes with a named group `v` (the PHI value itself), so the
span is exact and clinical words around it are kept. Names and places use spaCy NER via Presidio.
Safe Harbor types 16 (biometrics) and 17 (photos) do not occur in text.

Deliberately NOT redacted: relative times ("3 days ago"), doses ("2 tablets"), lab values,
and years on their own.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from presidio_analyzer import EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpArtifacts

_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
# USPS street suffixes (public list), so "12 Oak Lane" matches but "Take 2 Tylenol" does not
_STREET_SUFFIX = (
    r"(?:Alley|Annex|Arcade|Avenue|Ave|Bayou|Beach|Bend|Bluffs?|Bottom|Boulevard|Blvd|Branch|"
    r"Bridge|Brooks?|Burgs?|Bypass|Camp|Canyon|Cape|Causeway|Centers?|Circles?|Cliffs?|Club|"
    r"Common|Corners?|Course|Courts?|Ct|Coves?|Creek|Crescent|Crest|Crossing|Crossroad|Curve|"
    r"Dale|Dam|Divide|Drives?|Dr|Estates?|Expressway|Extensions?|Falls?|Ferry|Fields?|Flats?|"
    r"Fords?|Forest|Forges?|Forks?|Fort|Freeway|Gardens?|Gateway|Glens?|Greens?|Groves?|"
    r"Harbors?|Haven|Heights|Highway|Hwy|Hills?|Hollow|Inlet|Islands?|Isle|Junctions?|Keys?|"
    r"Knolls?|Lakes?|Land|Landing|Lane|Ln|Lights?|Loaf|Locks?|Lodge|Loop|Mall|Manors?|Meadows?|"
    r"Mews|Mills?|Mission|Motorway|Mount|Mountains?|Neck|Orchard|Oval|Overpass|Parks?|Parkways?|"
    r"Pass|Passage|Path|Pike|Pines?|Place|Pl|Plains?|Plaza|Points?|Ports?|Prairie|Radial|Ramp|"
    r"Ranch|Rapids?|Rest|Ridges?|River|Roads?|Rd|Route|Row|Rue|Run|Shoals?|Shores?|Skyway|"
    r"Springs?|Spurs?|Squares?|Station|Stravenue|Stream|Streets?|St|Summit|Terrace|Throughway|"
    r"Trace|Track|Trafficway|Trail|Trailer|Tunnel|Turnpike|Underpass|Unions?|Valleys?|Via|"
    r"Viaduct|Views?|Villages?|Ville|Vista|Walks?|Wall|Ways?|Wells?)"
)
_ID = r"[A-Z0-9][A-Z0-9-]{3,29}"
_LABEL_SEP = r"\s*(?:number|no\.?|num|#|id)?\s*[:#]?\s*"

PATTERNS: dict[str, list[str]] = {
    # 3. Dates (all elements except the year alone)
    "DATE": [
        r"\b(?P<v>\d{1,2}/\d{1,2}/\d{2,4})\b",
        r"\b(?P<v>\d{4}-\d{2}-\d{2})\b",
        rf"\b(?P<v>{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?)\b",
        rf"\b(?P<v>\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\.?(?:,?\s+\d{{4}})?)\b",
    ],
    # 3. Ages over 89
    "AGE_OVER_89": [
        r"\b(?P<v>(?:9\d|1[0-2]\d))(?=[-\s]?(?:years?|yrs?|y/?o)\b)",
        r"\bage[ds]?\s*:?\s*(?P<v>(?:9\d|1[0-2]\d))\b",
    ],
    # 4, 5. Telephone and fax numbers
    "PHONE": [
        r"(?<![\w-])(?P<v>(?:(?:\+?1|001)[-.\s]?)?(?:\(\d{3}\)\s?|\d{3}[-.\s]?)\d{3}[-.\s]?\d{4}"
        r"(?:\s*(?:x|ext\.?)\s*\d{1,5})?)(?![\w-])",
    ],
    # 6. Email addresses
    "EMAIL": [r"\b(?P<v>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"],
    # 7. Social Security numbers
    "SSN": [r"\b(?P<v>\d{3}-\d{2}-\d{4})\b"],
    # 8. Medical record numbers
    "MRN": [rf"(?i:\b(?:MRN|medical\s+record){_LABEL_SEP})(?P<v>{_ID})\b"],
    # 9. Health plan beneficiary numbers
    "HEALTH_PLAN_ID": [
        rf"(?i:\b(?:member|policy|health\s+plan|insurance|beneficiary|subscriber){_LABEL_SEP})"
        rf"(?P<v>{_ID})\b",
    ],
    # 10. Account numbers
    "ACCOUNT_NUMBER": [rf"(?i:\baccount{_LABEL_SEP})(?P<v>{_ID})\b"],
    # 11. Certificate / licence numbers
    "LICENSE_NUMBER": [
        rf"(?i:\b(?:licen[cs]e|certificate)(?!\s+plate){_LABEL_SEP})(?P<v>{_ID})\b",
    ],
    # 12. Vehicle identifiers (VIN, plates)
    "VEHICLE_ID": [
        r"\b(?P<v>[A-HJ-NPR-Z0-9]{17})\b",
        r"(?i:\b(?:licen[cs]e\s+)?plate" + _LABEL_SEP + r")(?P<v>[A-Z0-9-]{2,8})\b",
    ],
    # 13. Device identifiers and serial numbers
    "DEVICE_ID": [rf"(?i:\b(?:serial|device|UDI|implant){_LABEL_SEP})(?P<v>{_ID})\b"],
    # 14. URLs
    "URL": [r"(?P<v>\bhttps?://[^\s<>\"']+[^\s<>\"'.,;:)]|\bwww\.[^\s<>\"']+[^\s<>\"'.,;:)])"],
    # 15. IP addresses
    "IP_ADDRESS": [
        r"\b(?P<v>(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d))\b",
        r"(?<![\w:])(?P<v>(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4})(?![\w:])",
    ],
    # 2. Geographic units smaller than a state: street addresses and ZIP codes
    "STREET_ADDRESS": [
        rf"\b(?P<v>\d{{1,6}}\s+(?:[A-Z][a-zA-Z]+\s+){{1,3}}{_STREET_SUFFIX}\.?"
        r"(?:,?\s+(?:Apt\.?|Suite|Unit|#)\s*\w+)?)\b",
    ],
    "ZIP": [
        r"(?:\b[A-Z]{2}\s+|(?i:\bzip(?:\s*code)?\s*:?\s*))(?P<v>\d{5}(?:-\d{4})?)\b",
    ],
}
STRUCTURED_TYPES = frozenset(PATTERNS)
# Patterns anchored on a keyword ("account number ...") beat bare formats: a 10-digit account
# number also looks like a phone number, and the keyword says which one it is.
KEYWORD_ANCHORED = frozenset(
    {"MRN", "HEALTH_PLAN_ID", "ACCOUNT_NUMBER", "LICENSE_NUMBER", "DEVICE_ID", "AGE_OVER_89"}
)
KEYWORD_SCORE = 0.95
# Above spaCy NER's 0.85: an exact format (email, date, URL) beats a statistical name guess
FORMAT_SCORE = 0.9


@dataclass(frozen=True)
class _Compiled:
    entity: str
    regex: re.Pattern[str]


class RegexRecognizer(EntityRecognizer):
    """Presidio recogniser for regexes whose named group `v` is the exact PHI span."""

    def __init__(self, patterns: dict[str, list[str]] = PATTERNS) -> None:
        self._compiled = [
            _Compiled(entity, re.compile(p)) for entity, plist in patterns.items() for p in plist
        ]
        super().__init__(supported_entities=list(patterns), name="clinscribe-regex")

    def load(self) -> None:
        return None

    def analyze(
        self, text: str, entities: Sequence[str], nlp_artifacts: NlpArtifacts | None = None
    ) -> list[RecognizerResult]:
        results = []
        for compiled in self._compiled:
            if compiled.entity not in entities:
                continue
            score = KEYWORD_SCORE if compiled.entity in KEYWORD_ANCHORED else FORMAT_SCORE
            for match in compiled.regex.finditer(text):
                start, end = match.span("v")
                results.append(RecognizerResult(compiled.entity, start, end, score))
        return results
