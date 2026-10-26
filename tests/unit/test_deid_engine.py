"""De-ID engine behaviour on fixed synthetic text (no real PHI anywhere in this file)."""

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from privacy.deid.engine import Deidentifier, build_analyzer
from privacy.deid.store import InMemoryStore
from privacy.deid.types import DeidentifiedText


@pytest.fixture(scope="module")
def deid() -> Deidentifier:
    store = InMemoryStore(SecretStr(Fernet.generate_key().decode()))
    return Deidentifier(build_analyzer("en_core_web_md"), store)


@pytest.mark.parametrize(
    ("text", "value", "label"),
    [
        ("Seen on 03/14/1962 in clinic.", "03/14/1962", "DATE_"),
        ("Follow-up March 3, 2027.", "March 3, 2027", "DATE_"),
        ("A 94-year-old man.", "94", "AGE_OVER_89_"),
        ("Call (617) 555-0142 tomorrow.", "555-0142", "PHONE_"),
        ("Email jo.doe@example.org please.", "jo.doe@example.org", "EMAIL_"),
        ("SSN 123-45-6789 verified.", "123-45-6789", "SSN_"),
        ("MRN: 00482913 confirmed.", "00482913", "MRN_"),
        ("Member ID XK29384756 active.", "XK29384756", "HEALTH_PLAN_ID_"),
        ("Account number 4829103746 billed.", "4829103746", "ACCOUNT_NUMBER_"),
        ("Pacemaker serial number SN-4821-ABCD read.", "SN-4821-ABCD", "DEVICE_ID_"),
        ("VIN 1HGCM82633A004352 noted.", "1HGCM82633A004352", "VEHICLE_ID_"),
        ("Portal https://portal.example.org/p/123 used.", "portal.example.org", "URL_"),
        ("Login from 203.0.113.45 today.", "203.0.113.45", "IP_ADDRESS_"),
        ("Lives at 42 Maple Avenue, Apt 3.", "42 Maple Avenue", "STREET_ADDRESS_"),
        ("Springfield, MA 01103 address.", "01103", "ZIP_"),
    ],
)
def test_structured_phi_is_replaced(deid: Deidentifier, text: str, value: str, label: str) -> None:
    out = deid.deidentify(text, "enc-structured").text.text
    assert value not in out
    assert label in out


def test_clinical_content_is_kept(deid: Deidentifier) -> None:
    text = "Take 2 tablets twice daily for 3 days. BP 142/88, HbA1c 7.9%, glucose 10.2 mmol/L."
    result = deid.deidentify(text, "enc-clinical")
    assert result.text.text == text
    assert result.replacements == []


def test_output_is_deidentified_text(deid: Deidentifier) -> None:
    result = deid.deidentify("Call 617-555-0142.", "enc-type")
    assert isinstance(result.text, DeidentifiedText)
    assert result.text.source == "deid-service"


def test_same_value_same_surrogate_within_encounter(deid: Deidentifier) -> None:
    first = deid.deidentify("Call (617) 555-0142.", "enc-consistent").text.text
    second = deid.deidentify("Again 617.555.0142 and 617-555-0199.", "enc-consistent").text.text
    assert first == "Call PHONE_1."
    assert second == "Again PHONE_1 and PHONE_2."


def test_encounters_are_separate(deid: Deidentifier) -> None:
    deid.deidentify("Call 617-555-0100 and 617-555-0101.", "enc-a")
    out = deid.deidentify("Call 617-555-0101.", "enc-b").text.text
    assert out == "Call PHONE_1."


def test_reidentify_round_trip(deid: Deidentifier) -> None:
    original = "MRN 00482913, call 617-555-0142 on 03/14/2026."
    masked = deid.deidentify(original, "enc-round").text.text
    assert deid.reidentify(masked, "enc-round") == original


def test_deidentifying_twice_keeps_surrogates(deid: Deidentifier) -> None:
    once = deid.deidentify("Call 617-555-0142 on 03/14/2026.", "enc-twice").text.text
    twice = deid.deidentify(once, "enc-twice").text.text
    assert twice == once


def test_store_keeps_no_plaintext() -> None:
    store = InMemoryStore(SecretStr(Fernet.generate_key().decode()))
    surrogate = store.surrogate_for("enc-1", "PHONE", "617-555-0142")
    assert all(b"617" not in token for token in store._ciphertext.values())
    assert store.original_for("enc-1", surrogate) == "617-555-0142"


def test_a_mapping_lists_its_originals_for_one_encounter_only() -> None:
    # the data subject's copy (GDPR Art. 15, ADR-0022): type, surrogate and the original value
    store = InMemoryStore(SecretStr(Fernet.generate_key().decode()))
    store.surrogate_for("enc-a", "PERSON", "Ada Synthetic")
    store.surrogate_for("enc-a", "AGE_OVER_89", "93")
    store.surrogate_for("enc-b", "PERSON", "Cy Unrelated")
    assert store.entries("enc-a") == [
        ("AGE_OVER_89", "AGE_OVER_89_1", "93"),
        ("PERSON", "PERSON_1", "Ada Synthetic"),
    ]
