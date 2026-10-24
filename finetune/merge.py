"""Merge the LoRA adapter into its base model, so the de-ID service runs the tagger with
transformers alone (no peft at runtime).

  uv run --with peft==0.21.2 python -m finetune.merge [--adapter data/finetune/deid_ner_lora_v2]
Writes data/finetune/deid_ner_tagger/ (config, weights, tokenizer, labels), ~260 MB.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ["O", "B-PERSON", "I-PERSON", "B-LOCATION", "I-LOCATION"]


def main(argv: list[str] | None = None) -> int:
    from peft import PeftModel  # type: ignore[import-not-found, unused-ignore]
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--adapter", type=Path, default=ROOT / "data/finetune/deid_ner_lora_v2")
    parser.add_argument("--out", type=Path, default=ROOT / "data/finetune/deid_ner_tagger")
    args = parser.parse_args(argv)
    config = json.loads((args.adapter / "adapter_config.json").read_text(encoding="utf-8"))
    base = AutoModelForTokenClassification.from_pretrained(
        config["base_model_name_or_path"],
        num_labels=len(LABELS),
        id2label=dict(enumerate(LABELS)),
        label2id={label: i for i, label in enumerate(LABELS)},
    )
    merged = PeftModel.from_pretrained(base, str(args.adapter)).merge_and_unload()
    args.out.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(str(args.out))
    AutoTokenizer.from_pretrained(str(args.adapter)).save_pretrained(str(args.out))
    (args.out / "SOURCE.txt").write_text(
        f"Merged from {args.adapter.name} (LoRA r={config.get('r')}, base "
        f"{config['base_model_name_or_path']}); evals/reports/privacy/deid_lora_round2.md\n",
        encoding="utf-8",
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
