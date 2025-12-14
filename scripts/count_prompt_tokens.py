from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import tiktoken


@dataclass(frozen=True)
class PromptCount:
    file: str
    tokens: int
    bytes: int


def _encoding_for_model(model_name: str):
    try:
        return tiktoken.encoding_for_model(model_name)
    except Exception:
        # Good default for 4o/4o-mini family; avoids hard-failing on unknown model names.
        return tiktoken.get_encoding("o200k_base")


def _iter_prompt_files(prompts_dir: Path) -> Iterable[Path]:
    for p in sorted(prompts_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".txt", ".md"}:
            # Keep it tight: only prompt-like files.
            continue
        yield p


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "backend" / "app" / "prompts"
    if not prompts_dir.exists():
        raise SystemExit(f"Prompts dir not found: {prompts_dir}")

    tokenizer_model = os.getenv("NOMADIC_TOKENIZER_MODEL", "gpt-4o-mini").strip()
    enc = _encoding_for_model(tokenizer_model)

    rows: list[PromptCount] = []
    for path in _iter_prompt_files(prompts_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        rows.append(
            PromptCount(
                file=str(path.relative_to(repo_root)).replace("\\", "/"),
                tokens=len(enc.encode(text)),
                bytes=len(text.encode("utf-8", errors="replace")),
            )
        )

    rows.sort(key=lambda r: r.tokens, reverse=True)
    total_tokens = sum(r.tokens for r in rows)

    print(f"Tokenizer model: {tokenizer_model}")
    print(f"Prompts dir: {prompts_dir}")
    print("")
    print("| Prompt file | Tokens | Bytes |")
    print("|---|---:|---:|")
    for r in rows:
        print(f"| {r.file} | {r.tokens} | {r.bytes} |")
    print("")
    print(f"TOTAL TOKENS (all prompt files): {total_tokens}")

    out_path = repo_root / "prompt_token_counts.json"
    out_path.write_text(
        json.dumps(
            {
                "tokenizer_model": tokenizer_model,
                "rows": [r.__dict__ for r in rows],
                "total_tokens": total_tokens,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
