"""Prompt versions are immutable (ADR-0026). SPEC section 7 writes the prompt version into every
trace and audit record, which only identifies a prompt if one version names one text. The lock
(prompts/versions.lock) keeps the fingerprint of every prompt version ever locked; CI fails when a
prompt file's id@version is not locked, or no longer matches its fingerprint.

  uv run python -m llmops.prompt_lock           lock new versions (a locked one never changes)
  uv run python -m llmops.prompt_lock --check   list the problems; exit 1 if any (what CI checks)
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts"
LOCK = PROMPTS / "versions.lock"


def prompt_files(directory: Path = PROMPTS) -> list[Path]:
    """Production prompts and the trials in prompts/experiments/."""
    return sorted(directory.rglob("*.yaml"))


def ref(data: Mapping[str, Any]) -> str:
    """The prompt's name in traces and audit rows, e.g. "answer_cited@v1"."""
    return f"{data['id']}@v{data['version']}"


def fingerprint(data: Mapping[str, Any]) -> str:
    """SHA-256 of the parsed prompt: the text and every call setting. Comments and line endings
    do not count, since the model never sees them."""
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def scan(files: Iterable[Path], root: Path = ROOT) -> tuple[dict[str, dict[str, str]], list[str]]:
    """{ref: {file, sha256}} for the prompt files, and the refs declared by more than one."""
    found: dict[str, dict[str, str]] = {}
    problems = []
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        name, rel = ref(data), path.relative_to(root).as_posix()
        if name in found:
            problems.append(f"{name} is declared by both {found[name]['file']} and {rel}")
            continue
        found[name] = {"file": rel, "sha256": fingerprint(data)}
    return found, problems


def problems(
    lock: Mapping[str, Mapping[str, str]], found: Mapping[str, Mapping[str, str]]
) -> list[str]:
    out = []
    for name, entry in found.items():
        locked = lock.get(name)
        if locked is None:
            out.append(f"{name} ({entry['file']}) is not locked: run `just prompt-lock`")
        elif locked["sha256"] != entry["sha256"]:
            out.append(
                f"{name} ({entry['file']}) changed after it was locked: give it a new version "
                "(a version must name one text, since traces and audit rows record only it)"
            )
    return out


def load(path: Path = LOCK) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    loaded: dict[str, dict[str, str]] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report only; write nothing")
    args = parser.parse_args(argv)
    lock = load()
    found, duplicates = scan(prompt_files())
    issues = duplicates + problems(lock, found)
    changed = [i for i in issues if "not locked" not in i]
    if args.check or changed:
        for issue in issues:
            print(issue)
        if not issues:
            print(f"{len(found)} prompt versions, all locked and unchanged")
        return 1 if issues else 0
    added = sorted(set(found) - set(lock))
    lock.update({name: found[name] for name in added})  # locked entries are never replaced
    LOCK.write_text(
        json.dumps(dict(sorted(lock.items())), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"locked {', '.join(added) if added else 'nothing new'}; {len(lock)} versions in the lock"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
