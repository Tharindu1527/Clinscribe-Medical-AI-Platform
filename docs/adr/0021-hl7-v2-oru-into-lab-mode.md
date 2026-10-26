# ADR-0021: HL7 v2 lab results (ORU^R01) enter through Lab mode's review

Status: Proposed · Date: 2026-10-26

## Context

SPEC §8 (interoperability): "HL7 v2: one ORU^R01 lab message is converted into FHIR Observations
to show legacy integration", and §13 maps "FHIR R4, HL7" to it with integration tests as evidence.
Nothing had been built. Lab mode already turns a report PDF into preliminary Observations, checks
the report's name and birth date against the chosen record, and writes each value only after the
doctor confirms, with one approval token per resource (Phase 5). Lab results are clinical writes,
so an HL7 path must not bypass that review.

## Options

1. **A general HL7 v2 library** (`python-hl7`, `hl7apy`): full parsing and validation, one more
   dependency for four segments.
2. **A conversion engine** (Microsoft FHIR-Converter's Liquid templates, HAPI's HL7 v2 structures):
   wide coverage, but a .NET or JVM service and templates to maintain, and it would write FHIR
   without the doctor's review.
3. **A small reader for MSH, PID, OBR and OBX that produces Lab mode's `LabReport`**, so the
   message joins the existing review, identity check and approved writes.

## Decision

Option 3 (`agents/lab/hl7.py`, about 200 lines, no dependency). Separators and escape sequences
come from MSH; carriage-return, newline and MLLP-framed messages read the same. The message type
must be ORU^R01 and name one patient. A result is mapped only when it is numeric (NM), coded in
LOINC as a test the reference config knows, in the expected UCUM unit, with status F or C; any
other result is listed for the doctor with the reason, never guessed. The reporting lab's
abnormal flag is used when present, otherwise the flag comes from the interval. The identity
check gains the MRN (PID-3, the MR identifier) next to the name and birth date, so a message for
another patient is refused before confirmation. `parse_lab_report` on fhir-mcp and
`POST /v1/lab/parse` take either `pdf_base64` or `hl7_message` (exactly one). No model sees the
message.

## Consequences

- Measured (`just eval lab`, `evals/reports/lab/hl7_oru.md`): 20 Synthea patients' latest panels
  as ORU^R01 v2.5.1, 155/155 results mapped with the right LOINC code, exact value, unit and flag
  (16 abnormal); identity 20/20; wrong-patient control 20/20, every one caught by the MRN alone;
  the same result with newline endings and MLLP framing 20/20. Integration: message → pending
  values → confirmation → final Observations in HAPI; another patient's message refused (409).
- The sender and the reader are written by the same project, so this shows the mapping and the
  checks, not robustness to real senders: local codes instead of LOINC, structured numerics
  (`>60`), Z-segments, other versions and batches are not handled.
- Not an interface engine: no MLLP listener, no acknowledgements (ACK), no retries or queueing.
  A deployment would put a listener in front of the same API call, with the sender's identity as
  the requester.
- HL7 messages carry PHI (name, birth date, MRN). As with PDFs, the message is read in memory,
  never sent to a model, and audit rows hold counts and the format only.
