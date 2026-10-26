"""HL7 v2 lab results (ORU^R01) into Lab mode (SPEC section 8: "one ORU^R01 lab message is
converted into FHIR Observations"; ADR-0021). Deterministic: no model sees the message.

The message becomes the same `LabReport` a PDF becomes (agents/lab/parser.py), so it goes through
the same steps: preliminary Observations, the identity check against the chosen record (here the
MRN too), the doctor's confirmation, then one approved write per value.

Read: MSH (message type must be ORU^R01), PID (MRN from PID-3, name, birth date), OBR (collection
time), OBX (one result each). Mapped: numeric (NM) results coded in LOINC that the reference config
knows, with the expected unit and status F (final) or C (corrected). Everything else is listed for
the doctor in `unreadable_rows`, never guessed. Not an HL7 engine: no MLLP listener, no ACKs, no
batches, no Z-segments.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from agents.lab.parser import LabReport, LabResult, reference

FLAGS: dict[str, Literal["H", "L", "N"]] = {"H": "H", "HH": "H", "L": "L", "LL": "L", "N": "N"}
MAPPED_STATUS = {"F", "C"}  # final, corrected; P (preliminary), X, D, ... are not confirmed values
MLLP = "\x0b\x1c"


@dataclass(frozen=True)
class Encoding:
    field: str = "|"
    component: str = "^"
    repetition: str = "~"
    escape: str = "\\"
    subcomponent: str = "&"

    def unescape(self, text: str) -> str:
        """HL7 escape sequences (\\F\\ \\S\\ \\T\\ \\R\\ \\E\\ \\Xhh\\); others are dropped."""
        e = re.escape(self.escape)
        named = {
            "F": self.field,
            "S": self.component,
            "T": self.subcomponent,
            "R": self.repetition,
            "E": self.escape,
        }

        def one(match: re.Match[str]) -> str:
            code = match.group(1)
            if code in named:
                return named[code]
            if code.startswith("X") and re.fullmatch(r"X(?:[0-9A-Fa-f]{2})+", code):
                return bytes.fromhex(code[1:]).decode("latin-1")
            return ""

        return re.sub(rf"{e}([^{e}]*){e}", one, text)

    def escape_text(self, text: str) -> str:
        out = text.replace(self.escape, f"{self.escape}E{self.escape}")
        for char, code in (
            (self.field, "F"),
            (self.component, "S"),
            (self.subcomponent, "T"),
            (self.repetition, "R"),
        ):
            out = out.replace(char, f"{self.escape}{code}{self.escape}")
        return out


@dataclass(frozen=True)
class Segment:
    name: str
    fields: list[str]  # raw (still escaped); fields[0] is the segment name, as in HL7 numbering
    enc: Encoding

    def field(self, n: int) -> str:
        return self.fields[n] if n < len(self.fields) else ""

    def components(self, n: int, repetition: int = 0) -> list[str]:
        reps = self.field(n).split(self.enc.repetition)
        raw = reps[repetition] if repetition < len(reps) else ""
        return [self.enc.unescape(c) for c in raw.split(self.enc.component)]

    def component(self, n: int, c: int = 1) -> str:
        parts = self.components(n)
        return parts[c - 1].strip() if c - 1 < len(parts) else ""

    def repetitions(self, n: int) -> list[list[str]]:
        count = len(self.field(n).split(self.enc.repetition)) if self.field(n) else 0
        return [self.components(n, r) for r in range(count)]


def segments(message: str) -> list[Segment]:
    text = message.strip().strip(MLLP).strip()
    lines = [line for line in re.split(r"\r\n|\r|\n", text) if line.strip()]
    if not lines or not lines[0].startswith("MSH") or len(lines[0]) < 8:
        raise ValueError("no MSH segment")
    head = lines[0]
    enc = Encoding(
        field=head[3],
        component=head[4],
        repetition=head[5],
        escape=head[6],
        subcomponent=head[7] if head[8:9] == head[3] else "&",
    )
    out = []
    for line in lines:
        parts = line.split(enc.field)
        if parts[0] == "MSH":  # MSH-1 is the separator itself, MSH-2 the encoding characters
            parts = ["MSH", enc.field, *parts[1:]]
        out.append(Segment(parts[0], parts, enc))
    return out


def _date(value: str) -> str | None:
    match = re.match(r"^(\d{4})(\d{2})(\d{2})", value)
    if not match:
        return None
    return date(*(int(g) for g in match.groups())).isoformat()


def _number(value: str) -> float | None:
    return float(value) if re.fullmatch(r"-?\d+(?:\.\d+)?", value.strip()) else None


def parse_oru(message: str) -> LabReport:
    """ORU^R01 -> LabReport. ValueError if it is not one readable ORU^R01 for one patient."""
    segs = segments(message)
    msh = segs[0]
    if (msh.component(9, 1), msh.component(9, 2)) != ("ORU", "R01"):
        raise ValueError(f"message type {msh.field(9)!r} is not ORU^R01")
    pids = [s for s in segs if s.name == "PID"]
    if len(pids) != 1:
        raise ValueError(f"expected one PID segment, found {len(pids)}")
    pid = pids[0]
    ids = pid.repetitions(3)
    mr = [c[0] for c in ids if len(c) > 4 and c[4] == "MR"] or [c[0] for c in ids[:1]]
    family, given, more = (pid.component(5, i) for i in (1, 2, 3))
    obr = next((s for s in segs if s.name == "OBR"), None)
    by_name = {info["name"].lower(): code for code, info in reference().items()}
    ref = reference()
    results: list[LabResult] = []
    unreadable: list[str] = []
    for obx in (s for s in segs if s.name == "OBX"):
        label = f"OBX {obx.field(1) or '?'} ({obx.component(3, 2) or obx.component(3, 1)})"
        code, text, system = obx.component(3, 1), obx.component(3, 2), obx.component(3, 3)
        status = obx.component(11)
        value = _number(obx.component(5)) if obx.field(2) == "NM" else None
        if obx.field(2) != "NM":
            unreadable.append(f"{label}: value type {obx.field(2) or '?'}, not numeric")
            continue
        if value is None:
            unreadable.append(f"{label}: value {obx.component(5)!r} is not a number")
            continue
        if status not in MAPPED_STATUS:
            unreadable.append(f"{label}: result status {status or '?'}, not final")
            continue
        loinc = code if system == "LN" and code in ref else by_name.get(text.lower())
        info = ref.get(loinc) if loinc else None
        unit = obx.component(6, 1)
        low = high = None
        bounds = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$", obx.component(7))
        if bounds:
            low, high = float(bounds.group(1)), float(bounds.group(2))
        elif info:
            low, high = float(info["low"]), float(info["high"])
        flag = FLAGS.get(obx.component(8))  # the reporting lab's flag first
        if flag is None and low is not None and high is not None:
            flag = "H" if value > high else "L" if value < low else "N"
        results.append(
            LabResult(
                loinc=loinc,
                name=text or (info["name"] if info else code),
                value=value,
                unit=unit,
                low=low,
                high=high,
                flag=flag,
                unit_matches=info is not None and unit == info["unit"],
            )
        )
    return LabReport(
        patient_name=" ".join(p for p in (given, more, family) if p) or None,
        birth_date=_date(pid.component(7)),
        collected=_date(obr.component(7)) if obr else None,
        results=results,
        unreadable_rows=unreadable,
        mrn=mr[0] if mr and mr[0] else None,
    )


def build_oru(
    *,
    mrn: str,
    family: str,
    given: Sequence[str],
    birth_date: str,
    collected: str,
    results: Sequence[tuple[str, str, float, str, str, str]],
    message_id: str = "MSG00001",
) -> str:
    """A synthetic ORU^R01 (v2.5.1) for tests and the evaluation. `results`: (LOINC, name, value,
    UCUM unit, reference range "low-high", flag). Segments end with a carriage return."""
    enc = Encoding()
    esc = enc.escape_text
    when = collected.replace("-", "")
    born = birth_date.replace("-", "")
    lines = [
        f"MSH|^~\\&|SYNTH-LAB|SYNTH-LAB|CLINSCRIBE|CLINIC|{when}0800||ORU^R01^ORU_R01|"
        f"{esc(message_id)}|P|2.5.1",
        f"PID|1||{esc(mrn)}^^^SMARTHEALTHIT^MR||{esc(family)}^{esc(given[0] if given else '')}"
        f"^{esc(' '.join(given[1:]))}||{born}",
        f"OBR|1||{esc(message_id)}-1|24323-8^Comprehensive metabolic panel^LN|||{when}0800",
    ]
    for n, (loinc, name, value, unit, ref_range, flag) in enumerate(results, start=1):
        lines.append(
            f"OBX|{n}|NM|{esc(loinc)}^{esc(name)}^LN||{value:.15g}|{esc(unit)}^{esc(unit)}^UCUM|"
            f"{esc(ref_range)}|{flag}|||F|||{when}0800"
        )
    return "\r".join(lines) + "\r"
