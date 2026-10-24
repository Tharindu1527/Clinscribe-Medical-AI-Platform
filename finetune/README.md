# LoRA fine-tune of the de-ID name/place tagger (Phase 5)

The de-ID service finds structured PHI with rules and names/places with spaCy plus context cues
(ADR-0004): on the frozen held-out set names reach recall 0.973 and places 0.850. This folder holds
everything to train a small LoRA adapter for names and places on a free GPU.

## Round 1 (2026-10-19): trained, not adopted

`evals/reports/privacy/deid_lora_round1.md` (`uv run --with peft==0.21.2 python -m
evals.privacy.lora_eval --round 1`): on phrasings it never saw, the tagger found every name and place
(held-out v2: 110/110 and 70/70, vs spaCy 109/110 and 57/70), but it altered **15 of 80 and 13 of 40
PHI-free clinical sentences** (spaCy 0 and 3): it tags capitalised sentence starts ("Normal", "Lungs",
"Insulin"), acronyms and ward names. Cause: 9 of the 12 round-1 templates start with a name and there
were no PHI-free sentences. The de-ID service keeps spaCy.

## Round 2 (2026-10-19): trained, adopted behind `DEID_NER=tagger` (ADR-0014)

`evals/reports/privacy/deid_lora_round2.md`: on the sets frozen before round 2 was trained, names
90/90 and places 50/50 (spaCy 90/90 and 42/50), and 1 of 40 PHI-free sentences altered (spaCy 3).
To use it in the de-ID service:

1. `uv run --with peft==0.21.2 python -m finetune.merge` merges the adapter into
   `data/finetune/deid_ner_tagger/` (~250 MB; the service needs no peft).
2. In `.env`: `DEID_NER=tagger`, `DEID_TARGET=rag`, `DEID_IMAGE=clinscribe-python-rag:dev`,
   `DEID_MEM_LIMIT=3584m`; then `just up`.
3. `just eval privacy` (writes `deid_v2_tagger.md`) and `just eval leak` check it.

The steps that produced round 2:

1. `uv run python -m finetune.make_dataset` writes `data/finetune/deid_ner_v2/{train,dev,test}.jsonl`:
   12 more templates with names away from the sentence start, and ~40% PHI-free clinical sentences.
2. Open `finetune/deid_ner_lora.ipynb` in Google Colab, select a T4 GPU, run all cells and upload the
   three **deid_ner_v2** files when asked (a few minutes).
3. Download `deid_ner_lora.zip`, rename it `deid_ner_lora_v2.zip`, put it in `data/finetune/` and
   unzip it so the folder is `data/finetune/deid_ner_lora_v2/`.
4. `uv run --with peft==0.21.2 python -m evals.privacy.lora_eval --round 2`. The fair sets for round
   2 are held-out v3 and PHI-free v2 (written before round 2 was trained). Adopt the tagger only if
   it keeps recall and alters no more PHI-free sentences than spaCy.

Round 1 stays reproducible: `uv run python -m finetune.make_dataset --version 1`.
