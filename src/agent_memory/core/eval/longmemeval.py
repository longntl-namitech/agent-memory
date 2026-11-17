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
UNVERIFIED: the `question_type` names and row fields (question_id, question_type, question, answer,
question_date, haystack_*) come from the LongMemEval paper/README as remembered, not from the
downloaded files. Check them with `split_sizes()` on the real file; unknown types raise KeyError.

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
    return _TYPE_TO_ABILITY[row["question_type"]]


def _stream(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as out:
        while chunk := resp.read(1 << 20):  # chunked: files are hundreds of MB
            out.write(chunk)


def download(cache: Path, fetch=None) -> Path:
    """Fetch the two files into `cache` (skipping existing ones); return the s_cleaned path."""
    fetch = fetch or _stream
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        path = cache / name
        if path.exists():
            continue
        fd, tmp = tempfile.mkstemp(dir=cache, suffix=".tmp")
        os.close(fd)
        try:
            fetch(BASE_URL + name, Path(tmp))
            os.replace(tmp, path)  # atomic: a crash never leaves a half-written file
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


def full_context_subset(rows: list[dict], n: int = 10, seed: int = 7) -> list[dict]:
    """About `n` rows from the selected set, n // 5 per ability (10 -> 2 per ability)."""
    return _stratified(rows, n // len(ABILITIES), seed)
