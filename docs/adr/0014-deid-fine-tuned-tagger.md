# ADR-0014: De-ID names and places — the fine-tuned tagger behind `DEID_NER`

Status: Proposed · Date: 2026-10-24

## Context

De-ID v1 (ADR-0004) finds names and places with spaCy `en_core_web_md` plus context cues and a
clinical-term filter. On held-out sets written after its rules, spaCy misses places that come
without a cue: recall 0.850 (held-out v1), 0.814 (v2), 0.840 (v3). On PHI-free sentences it had not
been tuned on (PHI-free v2), it altered 3 of 40 ("FEV1" and "Bay 2" as places, "Sleeps" as a name).
SPEC §5 (Phase 5) plans a LoRA fine-tuned NER model for names in clinical speech.

A DistilBERT (`distilbert-base-cased`, Apache-2.0) token tagger with a LoRA adapter (r 8, q/v
projections) was trained on Colab on synthetic sentences only (`finetune/make_dataset.py`, Faker,
seeded), in two rounds. To keep the comparison honest, new test sets were frozen before any model
ran, and each report names the sets that were fair for that round.

## Options

All measured with `evals/privacy/lora_eval.py` through the same Presidio analyzer (structured-PHI
patterns, context cues and the clinical-term filter unchanged; only the name/place recogniser
differs). Fair sets for round 2: held-out v3 (90 names, 50 places) and PHI-free v2 (40 sentences).

| Option | Held-out v3 names | Held-out v3 places | PHI-free v2 altered | p50 / p95 per snippet |
|---|---|---|---|---|
| 1. spaCy (v1, current default) | 1.000 | 0.840 | 3 of 40 | 14.3 / 19.7 ms |
| 2. Tagger, round 1 (no PHI-free training sentences) | 0.978 | 1.000 | 13 of 40 (and 15 of 80 on v1) | 45.8 / 60.9 ms |
| 3. **Tagger, round 2** (+12 templates, ~40% PHI-free sentences) | **1.000** | **1.000** | **1 of 40** | 48.7 / 71.7 ms |
| 4. spaCy + tagger, round 2 (union) | 1.000 | 1.000 | 4 of 40 | 48.5 / 67.7 ms |

Round 1 tagged capitalised sentence starts, acronyms and ward names, because 9 of its 12 templates
start with a name and none was PHI-free (`evals/reports/privacy/deid_lora_round1.md`). The union
(option 4) adds no recall over option 3 and keeps spaCy's over-redaction.

## Decision

Option 3, behind a setting: `DEID_NER=tagger` uses the round-2 tagger in place of spaCy's NER (spaCy
still tokenises; context cues, the clinical-term filter and every structured pattern still run).
`DEID_NER=spacy` stays the default in code, in CI and on a fresh clone, because the merged model is
a trained artefact in the git-ignored `data/` folder and needs torch.

- The adapter is merged into the base model (`finetune/merge.py`), so the service needs only
  transformers and torch, not peft: `data/finetune/deid_ner_tagger/`, `model.safetensors`
  SHA-256 `fd702aeb78a3af8015eebfc26feb0f88ed538c11d1cdaa1dca7ed100f0c8bab9`.
- `privacy/deid/tagger.py` splits words exactly as the training data did, labels a word by its first
  sub-word, tags long texts in windows of 200 words, and continues a window the 512-token limit cuts
  short at the first word left out (an unseen word would otherwise be labelled "O", a leak).
- The service with the tagger runs on the `rag` image (torch) with a larger memory limit, set in
  `.env`: `DEID_TARGET=rag`, `DEID_IMAGE=clinscribe-python-rag:dev`, `DEID_MEM_LIMIT=3584m`.

As the configured service (`just eval privacy`, `evals/reports/privacy/deid_v2_tagger.md`): every
gate passes (structured types 1.000, seeded names and places 1.000, over-redaction 0 of 80),
held-out v1 names 0.991 and places 1.000 (spaCy 0.973 / 0.850).

## Consequences

- Places without a cue ("originally from X", "works in X"), the main gap left by ADR-0004, are found
  on every held-out set. One PHI-free sentence of 40 is still altered ("Moved to Ward 7 after the
  operation"), and one held-out v1 name is missed (`PERSON@h9`).
- All test sets are synthetic templates with Faker names and places, and the fair sets are small
  (90 names, 50 places, 40 sentences). Real dictation is the harder test; ASR transcripts from
  PriMock57 are the next check, and any further tuning needs another frozen set.
- Cost: about +35 ms per snippet at p50 on CPU (49 vs 14 ms in-process), and de-ID runs twice per
  question. Load test, same day and warm, back to back (`evals/reports/load/load_test.md`): about
  14% less throughput on average (5.3 → 4.1-4.9 req/s) and +0.3-1.8 s at p50 at 10-100 sessions,
  because the tagger competes with the guideline encoders for the same CPU cores. Memory: the de-ID
  service uses 2.1-2.3 GiB with 3 workers (each loads the model) vs 1.1 GiB with spaCy, against a
  3.5 GiB limit; the whole stack (core + fhir + rag) measured 5.9 GiB, within the 8 GB budget. The
  image grows from ~1 GB to ~2.7 GB.
- Leak test with the tagger (gate b, run `8697df2f`): 0 leaks in all 6 sinks, positive control
  100%, 0 of 66 seeded values reached the model (`evals/reports/privacy/leak_test.md`).
- The model is reproducible from `finetune/` (seeded data, the notebook), but Colab GPU training is
  not bit-for-bit deterministic: a retrained model needs `lora_eval.py --round 2` again before it
  replaces this one; the checksum above identifies the evaluated model.
- Rolling back is one line in `.env` (`DEID_NER=spacy`, and the three Compose variables removed),
  then `just up`.
- Update 2026-10-28 (ADR-0029): the tagger takes a role word at the start of a note sentence for a
  name ("Patient has been ...", "Wife has noticed ..."): 16 of 40 such PHI-free sentences altered,
  a class the PHI-free sets above did not cover. The engine now drops a model's guess that is only
  a role word; recall on every set is unchanged.
