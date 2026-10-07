"""Check retrieval/colbert.py against the ONNX export shipped in the model repository.

The checkpoint's authors publish `model.onnx` next to the weights. If our encoder (BERT + linear
projection + normalisation) is right, both give the same token vectors for the same inputs. The
tokenisation rules ([Q]/[D] markers, [MASK] augmentation) are covered by unit tests.

Run once, outside the project's dependencies (onnxruntime is not a project dependency):
  uv run --with onnxruntime python -m evals.rag.colbert_parity
"""

import importlib
import sys
from pathlib import Path
from typing import Any

import numpy as np
from huggingface_hub import snapshot_download

from retrieval.colbert import ColBERTEncoder, load_config

TEXTS = [
    "Which drugs increase the bleeding risk of warfarin?",
    "Metformin is the first-line medicine for type 2 diabetes; check renal function first.",
]


def main() -> int:
    ort: Any = importlib.import_module("onnxruntime")
    cfg = load_config()
    path = Path(snapshot_download(cfg.model, revision=cfg.revision, allow_patterns=["model.onnx"]))
    session = ort.InferenceSession(str(path / "model.onnx"), providers=["CPUExecutionProvider"])
    names = [i.name for i in session.get_inputs()]
    print("onnx inputs:", names, "outputs:", [(o.name, o.shape) for o in session.get_outputs()])
    encoder = ColBERTEncoder(cfg)
    worst = 0.0
    for kind, (ids, mask) in (
        ("query", encoder.query_inputs(TEXTS)),
        ("doc", encoder.doc_inputs(TEXTS)),
    ):
        ours = encoder._embed(ids, mask).numpy()
        feeds = {"input_ids": ids.numpy(), "attention_mask": mask.numpy()}
        if "token_type_ids" in names:
            feeds["token_type_ids"] = np.zeros_like(feeds["input_ids"])
        theirs = session.run(None, {k: v for k, v in feeds.items() if k in names})[0]
        theirs = theirs / np.linalg.norm(theirs, axis=-1, keepdims=True).clip(1e-12)
        # compare attended positions (and query [MASK] positions, which ColBERT also scores)
        keep = np.ones(ids.shape, dtype=bool) if kind == "query" else mask.numpy().astype(bool)
        diff = float(np.abs(ours[keep] - theirs[keep]).max())
        cosine = float((ours[keep] * theirs[keep]).sum(-1).min())
        print(f"{kind}: shape ours {ours.shape} onnx {theirs.shape}; max |diff| {diff:.2e}; "
              f"min cosine {cosine:.6f}")  # fmt: skip
        worst = max(worst, diff)
    ok = worst < 1e-3
    print("PARITY OK" if ok else "PARITY FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
