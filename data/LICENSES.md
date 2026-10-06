# Dataset licences

Every dataset is checked before download and recorded here (SPEC section 9).
Data files themselves live in `data/` and are git-ignored; only this file is committed.

| Dataset | Licence | Verified on | Source | Notes |
|---|---|---|---|---|
| Synthea v4.0.0 (generator + generated FHIR R4 patients) | Apache-2.0 | 2026-10-05 (GitHub licence API) | https://github.com/synthetichealth/synthea | Phase 1; jar SHA-256 pinned in `scripts/fhir_load.py` |
| PriMock57 | To verify | — | — | Phase 4 |
| ACI-Bench | To verify | — | — | Phase 3 |
| PubMed Central Open Access subset | Per article; to verify | — | — | Phase 2 |
| WHO guidelines | To verify | — | — | Phase 2 |
| DDInter | To verify | — | — | Phase 2 |
| RxNorm brand names (BN) and ingredients (IN), via the NLM RxNav REST API (`allconcepts`) | Public NLM data, free to use; RxNav API terms of service apply; no UMLS licence needed for these term types | 2026-10-06 | https://rxnav.nlm.nih.gov | De-ID v1 clinical lexicon (`privacy/deid/resources/clinical_lexicon.txt`, person names removed); Phase 4 keyterms |
| openFDA drug labels | US government data (openFDA terms: free, public domain) | — | https://open.fda.gov | Phase 2; checked 2026-10-06 but not used for the lexicon (count queries miss single-source brands) |
