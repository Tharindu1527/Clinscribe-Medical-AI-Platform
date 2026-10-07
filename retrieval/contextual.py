"""Contextual retrieval (ablation step 4): an LLM writes a short prefix that places each chunk in
its document, and the prefix is prepended to the chunk for the dense, BM25 and ColBERT indexes.

Adapted from Anthropic's method for a local 3B model with a 2,048-token context: the prompt holds
the document title, source and section heading plus the first words of the chunk's section, not
the whole document (prompts/contextual_prefix.yaml). Chunks are processed in corpus order, so
chunks of one section share their prompt prefix and Ollama can reuse its cache.

Corpus text is public guidance, not patient data (ADR-0001); it reaches the gateway as
DeidentifiedText with source "public-corpus". The batch key can call only the local model, so this
job never spends cloud quota. Prefixes are cached per chunk (resumable): a rerun only fills gaps.

Usage: uv run python -m retrieval.contextual [--limit N]
Output: data/corpus/contextual/v<version>/{prefixes.jsonl, chunks.jsonl, manifest.json}
"""

import argparse
import hashlib
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from privacy.deid.types import issue

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "corpus"
PROMPT_FILE = ROOT / "prompts" / "contextual_prefix.yaml"
SOURCE_NAMES = {"who": "WHO guideline", "openfda": "FDA drug label", "pmc": "review article"}
_PREAMBLE = re.compile(
    r"^\s*(here is the (succinct )?context:?|context:|succinct context:)\s*", re.IGNORECASE
)


class PromptSpec(BaseModel):
    id: str
    version: str
    task: str
    temperature: float
    max_tokens: int
    section_excerpt_words: int
    max_prefix_words: int
    system: str
    user: str


def load_prompt(path: Path = PROMPT_FILE) -> PromptSpec:
    return PromptSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def output_dir(spec: PromptSpec, corpus: Path = CORPUS) -> Path:
    return corpus / "contextual" / f"v{spec.version}"


def section_index(chunk_id: str) -> int:
    """'pmc:PMC1#s3#c0' -> 3 (chunk ids are '<doc>#s<section>#c<chunk>')."""
    return int(chunk_id.split("#")[1].removeprefix("s"))


def excerpts(docs: Sequence[dict[str, Any]], words: int) -> dict[tuple[str, int], str]:
    """First `words` words of every section, keyed by (doc id, section index)."""
    return {
        (doc["id"], i): " ".join(section["text"].split()[:words])
        for doc in docs
        for i, section in enumerate(doc["sections"])
    }


def messages_for(spec: PromptSpec, chunk: dict[str, str], excerpt: str) -> tuple[str, str]:
    user = spec.user.format(
        title=chunk["title"],
        source=SOURCE_NAMES.get(chunk["source"], chunk["source"]),
        section=chunk["section"],
        excerpt=excerpt,
        chunk=chunk["text"],
    )
    return spec.system, user


def clean(text: str, max_words: int) -> str:
    """Strip preambles, quotes and line breaks; cut at max_words."""
    text = _PREAMBLE.sub("", " ".join(text.split())).strip().strip('"').strip()
    words = text.split()
    return " ".join(words[:max_words])


def request_key(spec: PromptSpec, model: str, system: str, user: str) -> str:
    payload = json.dumps([spec.version, model, spec.temperature, system, user])
    return hashlib.sha256(payload.encode()).hexdigest()


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {row["id"]: row for row in rows}  # later lines win (a retried chunk)


Generate = Callable[[str, str], dict[str, Any]]


def generate_prefixes(
    spec: PromptSpec,
    model: str,
    chunks: Sequence[dict[str, str]],
    docs: Sequence[dict[str, Any]],
    generate: Generate,
    out: Path,
    limit: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Fill the prefix cache for every chunk (or the first `limit`); returns id -> cache row."""
    out.mkdir(parents=True, exist_ok=True)
    cache_path = out / "prefixes.jsonl"
    cache = load_cache(cache_path)
    sections = excerpts(docs, spec.section_excerpt_words)
    todo = []
    for chunk in chunks[:limit] if limit else chunks:
        system, user = messages_for(
            spec, chunk, sections[(chunk["doc_id"], section_index(chunk["id"]))]
        )
        key = request_key(spec, model, system, user)
        if cache.get(chunk["id"], {}).get("key") != key:
            todo.append((chunk["id"], key, system, user))
    started, done = time.perf_counter(), 0
    with cache_path.open("a", encoding="utf-8", newline="\n") as handle:
        for chunk_id, key, system, user in todo:
            result = generate(system, user)
            row = {
                "id": chunk_id,
                "key": key,
                **result,
                "prefix": clean(result["text"], spec.max_prefix_words),
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            cache[chunk_id] = row
            done += 1
            if done % 100 == 0 or done == len(todo):
                rate = done / (time.perf_counter() - started)
                print(
                    f"{done}/{len(todo)} prefixes, {rate:.2f}/s, "
                    f"~{(len(todo) - done) / rate / 60:.0f} min left",
                    file=sys.stderr,
                    flush=True,
                )
    return cache


def write_variant(
    chunks: Sequence[dict[str, str]], cache: dict[str, dict[str, Any]], out: Path, spec: PromptSpec
) -> dict[str, Any]:
    """Write the contextual corpus: same ids and metadata, text = prefix + blank line + chunk."""
    missing = [c["id"] for c in chunks if not cache.get(c["id"], {}).get("prefix")]
    if missing:
        raise SystemExit(f"{len(missing)} chunks have no prefix yet (first: {missing[0]}); rerun")
    lines = [
        json.dumps(
            {
                **c,
                "context": cache[c["id"]]["prefix"],
                "text": cache[c["id"]]["prefix"] + "\n\n" + c["text"],
            },
            ensure_ascii=False,
        )
        for c in chunks
    ]
    data = ("\n".join(lines) + "\n").encode("utf-8")
    (out / "chunks.jsonl").write_bytes(data)
    words = [len(cache[c["id"]]["prefix"].split()) for c in chunks]
    manifest = {
        "variant": f"contextual-v{spec.version}",
        "prompt": f"{spec.id}@v{spec.version}",
        "chunks": len(chunks),
        "chunks_sha256": hashlib.sha256(data).hexdigest(),
        "prefix_words_median": sorted(words)[len(words) // 2],
        "prefix_words_max": max(words),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def gateway_generator(spec: PromptSpec) -> tuple[str, Generate]:
    from config.settings import Settings
    from llmops.gateway.client import ChatMessage, GatewayClient, alias_for

    settings = Settings()
    if not settings.litellm_batch_key.get_secret_value():
        raise SystemExit("LITELLM_BATCH_KEY is empty: run `just gen-keys` and `just gateway-keys`")
    client = GatewayClient(settings.gateway_url, settings.litellm_batch_key, timeout=180.0)
    model = alias_for(spec.task)

    def generate(system: str, user: str) -> dict[str, Any]:
        messages = [
            ChatMessage("system", issue(system, "public-corpus")),
            ChatMessage("user", issue(user, "public-corpus")),
        ]
        for attempt in range(4):
            try:
                completion = client.complete(
                    model, messages, temperature=spec.temperature, max_tokens=spec.max_tokens
                )
                return {
                    "text": completion.text,
                    "ms": completion.latency_ms,
                    "in_tok": completion.input_tokens,
                    "out_tok": completion.output_tokens,
                }
            except Exception as exc:  # noqa: BLE001 - retried, then re-raised
                if attempt == 3:
                    raise
                print(f"retry {attempt + 1} after {type(exc).__name__}", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        raise AssertionError("unreachable")

    return model, generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate contextual prefixes for the corpus")
    parser.add_argument("--limit", type=int, help="only the first N chunks (pilot run)")
    args = parser.parse_args(argv)
    spec = load_prompt()

    def rows(name: str) -> list[dict[str, Any]]:
        return [json.loads(x) for x in (CORPUS / name).read_text(encoding="utf-8").splitlines()]

    chunks, docs = rows("chunks.jsonl"), rows("docs.jsonl")
    model, generate = gateway_generator(spec)
    out = output_dir(spec)
    cache = generate_prefixes(spec, model, chunks, docs, generate, out, limit=args.limit)
    if args.limit:
        print(f"pilot: {len(cache)} prefixes cached in {out / 'prefixes.jsonl'}")
        return 0
    print(json.dumps(write_variant(chunks, cache, out, spec), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())


def variant(name: str) -> tuple[Path, str]:
    """Corpus folder and index-name suffix for a corpus variant: "raw" or "contextual"."""
    if name == "raw":
        return CORPUS, ""
    if name == "contextual":
        spec = load_prompt()
        return output_dir(spec), f"_ctx_v{spec.version}"
    raise ValueError(f"unknown corpus variant {name!r}")
