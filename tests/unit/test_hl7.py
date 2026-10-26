"""HL7 v2 ORU^R01 into Lab mode (ADR-0021): reading the message, what is mapped and what is listed
for the doctor, the identity check with the MRN, and the fhir-mcp tool. No model, no stack."""

from typing import Any

import pytest
from pydantic import ValidationError

from agents.lab.hl7 import Encoding, build_oru, parse_oru
from agents.lab.parser import identity_matches, to_observation
from agents.schemas import ParseLabReportInput
from mcp_servers.fhir_mcp.server import build_server as fhir_server
from tests.unit.test_mcp_servers import KEY, NOW, FakeAudit, FakeStore, call

pytestmark = pytest.mark.unit
RESULTS = [
    ("2339-0", "Glucose", 131.0, "mg/dL", "70-99", "H"),
    ("6298-4", "Potassium", 4.2, "mmol/L", "3.5-5.1", "N"),
    ("33914-3", "eGFR", 72.5, "mL/min/{1.73_m2}", "60-200", "N"),
]
MESSAGE = build_oru(
    mrn="mrn-42",
    family="Kuhn96",
    given=["Ada", "May"],
    birth_date="1930-05-04",
    collected="2025-09-09",
    results=RESULTS,
)
RECORD: dict[str, Any] = {
    "resourceType": "Patient",
    "id": "p-1",
    "birthDate": "1930-05-04",
    "name": [{"family": "Kuhn96", "given": ["Ada", "May"]}],
    "identifier": [
        {"type": {"coding": [{"code": "SS"}]}, "value": "999-00-1111"},
        {"type": {"coding": [{"code": "MR"}]}, "value": "mrn-42"},
    ],
}


def test_round_trip_reads_patient_collection_and_results() -> None:
    report = parse_oru(MESSAGE)
    assert (report.patient_name, report.birth_date, report.collected, report.mrn) == (
        "Ada May Kuhn96",
        "1930-05-04",
        "2025-09-09",
        "mrn-42",
    )
    got = [
        (r.loinc, r.value, r.unit, r.low, r.high, r.flag, r.unit_matches) for r in report.results
    ]
    assert got == [
        ("2339-0", 131.0, "mg/dL", 70.0, 99.0, "H", True),
        ("6298-4", 4.2, "mmol/L", 3.5, 5.1, "N", True),
        ("33914-3", 72.5, "mL/min/{1.73_m2}", 60.0, 200.0, "N", True),
    ]
    assert report.unreadable_rows == []
    obs = to_observation(report.results[0], "p-1", report.collected)
    assert (obs["status"], obs["code"]["coding"][0]["code"]) == ("preliminary", "2339-0")
    assert obs["effectiveDateTime"] == "2025-09-09"


@pytest.mark.parametrize(
    "framed",
    [
        MESSAGE.replace("\r", "\n"),  # pasted from a text file
        MESSAGE.replace("\r", "\r\n"),
        f"\x0b{MESSAGE}\x1c\r",  # MLLP framing as it comes off the wire
    ],
)
def test_line_endings_and_mllp_framing_read_the_same(framed: str) -> None:
    assert parse_oru(framed) == parse_oru(MESSAGE)


def test_escape_sequences_and_other_separators() -> None:
    enc = Encoding()
    tricky = "O|Brien^&~\\"
    assert enc.unescape(enc.escape_text(tricky)) == tricky
    message = build_oru(
        mrn="m^1",
        family=tricky,
        given=["Ann"],
        birth_date="1950-01-02",
        collected="2025-01-01",
        results=RESULTS[:1],
    )
    report = parse_oru(message)
    assert (report.patient_name, report.mrn) == (f"Ann {tricky}", "m^1")
    assert enc.unescape("\\X41\\\\X4243\\") == "ABC"
    hashes = MESSAGE.replace("|", "#")  # a sender with another field separator
    assert parse_oru(hashes).results == parse_oru(MESSAGE).results


def test_the_mr_identifier_is_chosen_among_repetitions() -> None:
    message = MESSAGE.replace(
        "PID|1||mrn-42^^^SMARTHEALTHIT^MR", "PID|1||999-00-1111^^^SSA^SS~mrn-42^^^SMARTHEALTHIT^MR"
    )
    assert parse_oru(message).mrn == "mrn-42"


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda m: m.replace("ORU^R01^ORU_R01", "ADT^A01^ADT_A01"), "not ORU"),
        (lambda m: m.replace("\rOBR", "\rPID|2||x^^^A^MR||Other^One||19800101\rOBR"), "one PID"),
        (lambda m: m.replace("MSH|", "XXX|"), "no MSH"),
    ],
)
def test_messages_that_are_not_one_oru_for_one_patient_are_refused(change: Any, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        parse_oru(change(MESSAGE))


def test_results_that_are_not_confirmed_numbers_are_listed_not_mapped() -> None:
    lines = MESSAGE.rstrip("\r").split("\r")
    lines += [
        "OBX|4|ST|2339-0^Glucose^LN||see comment|mg/dL^mg/dL^UCUM|70-99||||F",
        "OBX|5|NM|6298-4^Potassium^LN||4.9|mmol/L^mmol/L^UCUM|3.5-5.1|N|||P",
        "OBX|6|NM|2947-0^Sodium^LN||1x40|mmol/L^mmol/L^UCUM|135-145|N|||F",
        "OBX|7|NM|99999-9^Mystery^LN||3|U^U^UCUM|1-2|H|||F",
        "OBX|8|NM|2947-0^Sodium^LN||140|mg/dL^mg/dL^UCUM|135-145|N|||F",
    ]
    report = parse_oru("\r".join(lines))
    assert report.unreadable_rows == [
        "OBX 4 (Glucose): value type ST, not numeric",
        "OBX 5 (Potassium): result status P, not final",
        "OBX 6 (Sodium): value '1x40' is not a number",
    ]
    mystery, wrong_unit = report.results[3], report.results[4]
    assert mystery.loinc is None
    assert (wrong_unit.loinc, wrong_unit.unit_matches) == ("2947-0", False)
    for result in (mystery, wrong_unit):
        with pytest.raises(ValueError, match="unknown test or unexpected unit"):
            to_observation(result, "p-1", report.collected)


def test_the_reporting_labs_flag_comes_first() -> None:
    critical = MESSAGE.replace("|70-99|H|", "|70-99|HH|")
    assert parse_oru(critical).results[0].flag == "H"
    unflagged = MESSAGE.replace("|3.5-5.1|N|", "|3.5-5.1||")  # 4.2: computed from the range
    assert parse_oru(unflagged).results[1].flag == "N"


def test_identity_includes_the_mrn_when_the_message_carries_one() -> None:
    report = parse_oru(MESSAGE)
    assert identity_matches(report, RECORD) == {"name": True, "birth_date": True, "mrn": True}
    other = {**RECORD, "identifier": [{"type": {"coding": [{"code": "MR"}]}, "value": "mrn-7"}]}
    assert identity_matches(report, other)["mrn"] is False
    printed = report.model_copy(update={"mrn": None})  # a PDF names no record
    assert "mrn" not in identity_matches(printed, RECORD)


def test_the_tool_takes_exactly_one_report() -> None:
    base = {"patient_id": "p-1", "requested_by": "dr", "role": "doctor"}
    ParseLabReportInput.model_validate({**base, "hl7_message": MESSAGE})
    with pytest.raises(ValidationError, match="exactly one"):
        ParseLabReportInput.model_validate(base)
    with pytest.raises(ValidationError, match="exactly one"):
        ParseLabReportInput.model_validate(
            {**base, "hl7_message": MESSAGE, "pdf_base64": "JVBERi0xLjQK"}
        )


class RecordStore(FakeStore):
    def read(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
        return RECORD if (resource_type, resource_id) == ("Patient", "p-1") else None


def test_fhir_mcp_parses_a_message_and_audits_the_format() -> None:
    audit = FakeAudit()
    server = fhir_server(RecordStore(), audit, KEY, clock=lambda: NOW)
    request = {"hl7_message": MESSAGE, "patient_id": "p-1", "requested_by": "dr", "role": "doctor"}
    error, result = call(server, "parse_lab_report", request)
    assert not error, result
    assert result["identity"] == {"name": True, "birth_date": True, "mrn": True}
    assert result["abnormal"] == ["Glucose 131 mg/dL (H)"]
    assert [o["status"] for o in result["observations"]] == ["preliminary"] * 3
    [entry] = audit.entries
    assert (entry.action, entry.details["format"]) == ("lab.parse", "hl7v2")
    error, message = call(server, "parse_lab_report", {**request, "hl7_message": "MSH|bad msg"})
    assert error
    assert "not a readable HL7 v2 ORU^R01 message" in message
