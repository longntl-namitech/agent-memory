"""LongMemEval data download and subset selection.

Data: Hugging Face `xiaowu0162/longmemeval-cleaned` (MIT). File names confirmed from the dataset
card: `longmemeval_s_cleaned.json` (about 115k tokens of history per question) and
`longmemeval_oracle.json`. Only these two are fetched, into a cache dir (`.cache/`, git-ignored).

Ability mapping (the five LongMemEval abilities), from `question_type` plus the `_abs` id suffix:
  abstention              - question_id ends with `_abs` (checked first, any question_type)
  information extraction  - single-session-user, single-session-assistant, single-session-preference
  multi-session reasoning - multi-session
  knowledge updates       - knowledge-update
  temporal reasoning      - temporal-reasoning
Verified against the LongMemEval GitHub README (https://github.com/xiaowu0162/LongMemEval) and the
Hugging Face dataset card: the question_type names above, the `_abs` rule (30 of 500 questions, inside
the other types' rows) and the file names. Not fetched: the `resolve/main` URL pattern. An unknown
question_type raises ValueError.

Sizes, measured on 2026-11-17: s_cleaned is 277,383,467 bytes, oracle is 15,388,478 bytes. Json-loading
s_cleaned needs roughly 1-3 GB RAM (UNVERIFIED). The runner loads it once, selects, and writes the selected
50 to a small JSON in `.cache/`.

Download integrity: the first real download stopped at 226,889,973 bytes (JSON cut mid-string). `_stream`
compares the bytes written with the server size and `download` retries a short fetch up to 3 times, never
promoting an incomplete file. Each good file gets a `<name>.size` sidecar with the server byte count; an
existing file whose size differs from its sidecar (or, with no sidecar, whose last non-whitespace byte is
not `]`) is fetched again.

Split sizes of the cleaned split must be checked at download time (spec caveat): `split_sizes`.
"""
import json
import os
import random
import tempfile
import urllib.request
from pathlib import Path

BASE_URL = "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/"
FILES = ("longmemeval_s_cleaned.json", "longmemeval_oracle.json")
ABILITIES = ("information extraction", "multi-session reasoning", "knowledge updates",
             "temporal reasoning", "abstention")
_TYPE_TO_ABILITY = {
    "single-session-user": ABILITIES[0],
    "single-session-assistant": ABILITIES[0],
    "single-session-preference": ABILITIES[0],
    "multi-session": ABILITIES[1],
    "knowledge-update": ABILITIES[2],
    "temporal-reasoning": ABILITIES[3],
}


def ability(row: dict) -> str:
    if str(row["question_id"]).endswith("_abs"):
        return "abstention"
    try:
        return _TYPE_TO_ABILITY[row["question_type"]]
    except KeyError:
        raise ValueError(
            f"unknown question_type {row['question_type']!r} (question_id {row['question_id']!r})"
        ) from None


def _stream(url: str, dest: Path) -> int | None:
    """Write `url` to `dest`; return the server size (None if no size header) and raise if fewer bytes arrived.

    The size comes from `Content-Length` of the final response (urllib follows the CDN redirect), else
    `X-Linked-Size`. With neither header the truncation check is skipped.
    """
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as out:
        size = resp.headers.get("Content-Length") or resp.headers.get("X-Linked-Size")
        size = int(size) if size and size.isdigit() else None
        got = 0
        while chunk := resp.read(1 << 20):  # chunked: files are hundreds of MB
            out.write(chunk)
            got += len(chunk)
    if size is not None and got < size:
        raise RuntimeError(f"download truncated: got {got} of {size} bytes for {Path(url).name}")
    return size


def _is_complete(path: Path) -> bool:
    sidecar = path.with_name(path.name + ".size")
    if sidecar.exists():
        return sidecar.read_text().strip() == str(path.stat().st_size)
    with open(path, "rb") as f:  # no sidecar: cheap check, a JSON array ends with `]`
        f.seek(max(0, path.stat().st_size - 4096))
        return f.read().rstrip()[-1:] == b"]"


def download(cache: Path, fetch=None, expected_sizes: dict[str, int] | None = None, attempts: int = 3) -> Path:
    """Fetch the two files into `cache` (skipping complete ones); return the s_cleaned path.

    `fetch(url, dest)` may return the expected size in bytes (the real `_stream` does); `expected_sizes`
    (file name -> bytes) supplies it for a fake fetch. With no size known the check is skipped. A short or
    failed fetch is retried up to `attempts` times with a full re-fetch, then the last error is raised.
    """
    fetch = fetch or _stream
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        path = cache / name
        if path.exists() and _is_complete(path):
            continue
        for attempt in range(attempts):
            fd, tmp = tempfile.mkstemp(dir=cache, suffix=".tmp")
            os.close(fd)
            try:
                size = fetch(BASE_URL + name, Path(tmp))
                size = size or (expected_sizes or {}).get(name)
                got = os.path.getsize(tmp)
                if size is not None and got < size:
                    raise RuntimeError(f"download truncated: got {got} of {size} bytes for {name}")
                os.replace(tmp, path)  # atomic: a crash never leaves a half-written file
                sidecar = path.with_name(name + ".size")
                if size is not None:
                    sidecar.write_text(str(size))
                elif sidecar.exists():
                    sidecar.unlink()  # stale size from an older file
                break
            except Exception:
                if attempt == attempts - 1:
                    raise
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
    return cache / FILES[0]


def split_sizes(path: Path) -> dict[str, int]:
    """Question count plus count per question_type (loads the whole file: use on oracle)."""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    sizes = {"questions": len(rows)}
    for r in rows:
        sizes[r["question_type"]] = sizes.get(r["question_type"], 0) + 1
    return sizes


def _stratified(rows: list[dict], per: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for a in ABILITIES:
        pool = sorted((r for r in rows if ability(r) == a), key=lambda r: r["question_id"])
        out += rng.sample(pool, min(per, len(pool)))
    return sorted(out, key=lambda r: (ABILITIES.index(ability(r)), r["question_id"]))


def select_subset(rows: list[dict], per_ability: int = 10, seed: int = 7) -> list[dict]:
    """Seeded, input-order-independent sample of `per_ability` rows per ability (fewer if short)."""
    return _stratified(rows, per_ability, seed)


def full_context_subset(rows: list[dict], n: int = 10) -> list[dict]:
    """Subset of `rows` (pass the selected set): first n // 5 per ability by question_id. No sampling."""
    out = []
    for a in ABILITIES:
        pool = sorted((r for r in rows if ability(r) == a), key=lambda r: r["question_id"])
        out += pool[: n // len(ABILITIES)]
    return out


def first_questions(rows: list[dict], n: int) -> list[dict]:
    """First `n` of `rows` stratified evenly: round-robin over the abilities, each pool by question_id."""
    pools = [sorted((r for r in rows if ability(r) == a), key=lambda r: r["question_id"]) for a in ABILITIES]
    out = []
    for i in range(max(map(len, pools), default=0)):
        out += [p[i] for p in pools if i < len(p)]
    return out[:n]


def load_selected(cache: Path, per_ability: int = 10, seed: int = 7, download_fn=None) -> list[dict]:
    """The selected rows, from a small `.cache/longmemeval_selected_<per>_<seed>.json` written on first use.

    The big s_cleaned file is json-loaded only when the small file is missing. `download_fn(cache)` fetches it
    when it is missing too; without one a missing file raises FileNotFoundError.
    """
    cache = Path(cache)
    small = cache / f"longmemeval_selected_{per_ability}_{seed}.json"
    if not small.exists():
        src = cache / FILES[0]
        if not src.exists():
            if download_fn is None:
                raise FileNotFoundError(f"{src} is missing; pass --download to fetch it")
            src = download_fn(cache)
        try:
            data = json.loads(Path(src).read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(
                f"{src} is not valid JSON ({e}); it looks truncated or corrupt. Delete it and re-run "
                "with --download to fetch it again."
            ) from e
        rows = select_subset(data, per_ability, seed)
        fd, tmp = tempfile.mkstemp(dir=cache, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        os.replace(tmp, small)
    return json.loads(small.read_text(encoding="utf-8"))
