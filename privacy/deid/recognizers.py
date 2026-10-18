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
# Between the parts of a date as speech recognition writes it: "21 12 1986", "21.12.1986",
# "21 12 at 1986" (Deepgram for "twenty-one twelve and nineteen eighty-six")
_DATE_SEP = r"(?:\s*[./-]\s*|\s+(?:(?:and|at|of)\s+)?)"
# A UK postcode, and the same spelled out by speech recognition ("N W 36 P Q" for NW3 6PQ)
_UK_POSTCODE = r"[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}"
_UK_POSTCODE_SPOKEN = r"[A-Z](?:\s[A-Z])?\s\d{1,2}(?:\s?[A-Z\d])?(?:\s\d)?\s[A-Z]\s?[A-Z]"
_LABEL_SEP = r"\s*(?:number|no\.?|num|#|id)?\s*[:#]?\s*"

PATTERNS: dict[str, list[str]] = {
    # 3. Dates (all elements except the year alone)
    "DATE": [
        r"\b(?P<v>\d{1,2}/\d{1,2}/\d{2,4})\b",
        r"\b(?P<v>\d{4}-\d{2}-\d{2})\b",
        rf"\b(?P<v>{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?)\b",
        rf"\b(?P<v>\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\.?(?:,?\s+\d{{4}})?)\b",
        # spoken numeric dates (Scribe from audio), with a four-digit year so "BP 140 90" is kept
        rf"\b(?P<v>\d{{1,2}}(?:st|nd|rd|th)?{_DATE_SEP}\d{{1,2}}{_DATE_SEP}(?:19|20)\d{{2}})\b",
        # any day-month-year after a date-of-birth cue, two-digit years included
        rf"(?i:\b(?:date\s+of\s+birth|DOB|D\.O\.B\.?|born\s+on)\b[^0-9\n]{{0,15}})"
        rf"(?P<v>\d{{1,2}}{_DATE_SEP}\d{{1,2}}{_DATE_SEP}\d{{2,4}})\b",
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
        # UK postcodes (PriMock57 is British): the written form anywhere; the spelled-out form only
        # after an address word in the same sentence, as spaced capitals are too common otherwise
        rf"\b(?P<v>{_UK_POSTCODE})\b",
        r"(?i:\b(?:post\s*code|address|street|road|lane|avenue|close|drive|way|crescent)\b"
        rf"[^.\n]{{0,60}}?)\b(?P<v>{_UK_POSTCODE_SPOKEN})\b",
    ],
}
STRUCTURED_TYPES = frozenset(PATTERNS)

# Names and places found from context cues (de-ID v1). spaCy alone missed names after relation words
# and invented towns in address lines; a cue makes the span unambiguous. Measured in deid_eval.
_NAME = r"[A-Z][a-zA-Z'’-]*[a-z]"  # Smith, McDonald, O'Brien, Smith-Jones; not ICU or BP
_NAMES_2_3 = rf"{_NAME}(?:\s+{_NAME}){{1,2}}"
_NAMES_1_4 = rf"{_NAME}(?:\s+{_NAME}){{0,3}}"
_TITLE = r"(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof)\.?"
_RELATION = (
    r"(?:[Dd]aughter|[Ss]on|[Ww]ife|[Hh]usband|[Mm]other|[Ff]ather|[Ss]ister|[Bb]rother|[Pp]artner|"
    r"[Ss]pouse|[Cc]aregiver|[Cc]arer|[Gg]uardian|[Nn]ext of kin|[Ee]mergency contact|[Cc]ontact|"
    r"[Pp]atient|[Pp]t|[Nn]ame)"
)
_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|"
    "NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|PR"
)
CONTEXT_PATTERNS: dict[str, list[str]] = {
    "PERSON": [
        # a title before one to three name words: "Dr. Wells", "Mrs. Taylor Smith"
        rf"\b{_TITLE}\s+(?P<v>{_NAME}(?:\s+{_NAME}){{0,2}})",
        # a relation or role word before a full name: "Daughter Morgan Marsh", "Patient: Ada Jones"
        rf"\b{_RELATION}\s*:?\s+(?:{_TITLE}\s+)?(?P<v>{_NAMES_2_3})",
        # a full name right before an identifier: "Tiffany Holloway (MRN", "Ada Jones, DOB"
        rf"(?P<v>{_NAMES_2_3})(?=\s*[,(]\s*(?:MRN|DOB|D\.O\.B\.?|SSN|NHS|date of birth)\b)",
    ],
    "LOCATION": [
        # a town before a US state code in an address: "Jacquelineland, MA 02115"
        rf"(?P<v>{_NAMES_1_4}),\s+(?:{_STATES})\b(?![a-z])",
        # residence and travel: "lives in Springfield", "moved to New Barry"
        rf"\b(?:lives|living|lived|resides|residing|moved|relocated|visiting|visited|travel(?:l)?ed|"
        rf"returned|arrived|born)\s+(?:in|at|near|to|from)\s+(?P<v>{_NAMES_1_4})",
        # referral source: "Referred by Dr. Ada Jones from New Barry"
        rf"\b(?:[Rr]eferred|[Tt]ransferred|[Ss]ent)\b[^\n;]{{0,80}}?\bfrom\s+(?P<v>{_NAMES_1_4})",
    ],
}
CUE_SCORE = 0.88  # above spaCy (0.85), below exact formats (0.9)
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

    def __init__(
        self,
        patterns: dict[str, list[str]] = PATTERNS,
        name: str = "clinscribe-regex",
        score: float | None = None,
    ) -> None:
        self._compiled = [
            _Compiled(entity, re.compile(p)) for entity, plist in patterns.items() for p in plist
        ]
        self._fixed_score = score
        self._recognizer_name: str = name  # Presidio's own `name` attribute is untyped
        super().__init__(supported_entities=list(patterns), name=name)

    def load(self) -> None:
        return None

    def analyze(
        self, text: str, entities: Sequence[str], nlp_artifacts: NlpArtifacts | None = None
    ) -> list[RecognizerResult]:
        results = []
        for compiled in self._compiled:
            if compiled.entity not in entities:
                continue
            if self._fixed_score is not None:
                score = self._fixed_score
            else:
                score = KEYWORD_SCORE if compiled.entity in KEYWORD_ANCHORED else FORMAT_SCORE
            for match in compiled.regex.finditer(text):
                start, end = match.span("v")
                results.append(
                    RecognizerResult(
                        compiled.entity,
                        start,
                        end,
                        score,
                        recognition_metadata={
                            RecognizerResult.RECOGNIZER_NAME_KEY: self._recognizer_name
                        },
                    )
                )
        return results
