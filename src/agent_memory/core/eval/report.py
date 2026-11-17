"""Markdown result writer with the fixed header. Never reads the clock: the caller passes run_date."""

import dataclasses
import os
import tempfile
from pathlib import Path


def _lines(value, indent: int = 0) -> list[str]:
    pad = "  " * indent
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    if not isinstance(value, dict):
        return [f"{pad}{value}"]
    out = []
    for k, v in value.items():  # insertion order kept: weeks must stay in sequence
        if dataclasses.is_dataclass(v) and not isinstance(v, type):
            v = dataclasses.asdict(v)
        if isinstance(v, dict):
            out.append(f"{pad}- {k}:")
            out += _lines(v, indent + 1)
        else:
            out.append(f"{pad}- {k}: {v}")
    return out


def write_result(path, *, eval_name, config, model, embedding_model, subset, seed, tokens,
                 metrics, extra: dict | None = None, run_date: str | None = None) -> None:
    extra = extra or {}
    out = ["PARTIAL RESULT", ""] if extra.get("partial") else []
    out += [
        f"# {eval_name} - {config}", "",
        f"- date: {run_date or 'unknown'}",
        f"- model: {model}",
        f"- embedding model: {embedding_model}",
        f"- subset: {subset}",
        f"- seed: {seed}",
        f"- tokens: {tokens}",
    ]
    out += [f"- {k}: {extra[k]}" for k in sorted(extra) if k != "partial"]
    out += ["", "## Metrics", ""] + _lines(metrics)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="\n", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
