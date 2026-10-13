# LoRA fine-tune of the de-ID name/place tagger (Phase 5)

The de-ID service finds structured PHI with rules and names/places with spaCy plus context cues
(ADR-0004): on the frozen held-out set names reach recall 0.973 and places 0.850. This folder holds
everything to train a small LoRA adapter for names and places on a free GPU.

1. `uv run python -m finetune.make_dataset` writes `data/finetune/deid_ner/{train,dev,test}.jsonl`
   (synthetic; Faker names and places; hard negatives such as eponyms, place-named diseases and drug
   brands tagged O).
2. Open `finetune/deid_ner_lora.ipynb` in Google Colab (or Kaggle), select a T4 GPU, run all cells and
   upload the three files when asked. Training takes a few minutes.
3. Download `deid_ner_lora.zip` (adapter, tokenizer, `test_report.txt`) into `data/finetune/`.

Not done yet (needs the trained adapter): loading the adapter in `privacy/deid` as an additional
recogniser and comparing it with spaCy on the frozen held-out set (`just eval privacy`), keeping
whichever is better on recall without raising over-redaction. Synthetic test-set scores from the
notebook are optimistic: the held-out set and real transcripts are the evaluation that counts.
