import json
from pathlib import Path

import pytest

from agent_memory.core.eval import longmemeval as lme

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "longmemeval_mini.json"
QTYPES = ["single-session-user", "multi-session", "knowledge-update", "temporal-reasoning"]


def make_rows(n_per=12):
    rows = []
    for t in QTYPES:
        rows += [{"question_id": f"{t}-{i}", "question_type": t} for i in range(n_per)]
    rows += [{"question_id": f"abs-{i}_abs", "question_type": "single-session-user"} for i in range(n_per)]
    return rows


def test_ability_mapping():
    assert lme.ability({"question_id": "x_abs", "question_type": "multi-session"}) == "abstention"
    assert lme.ability({"question_id": "x", "question_type": "single-session-preference"}) == "information extraction"


def test_stratified_10_per_ability():
    rows = make_rows()
    out = lme.select_subset(rows)
    assert len(out) == 50
    for a in lme.ABILITIES:
        assert sum(lme.ability(r) == a for r in out) == 10


def test_short_ability_does_not_crash():
    rows = make_rows(3)
    assert len(lme.select_subset(rows)) == 15


def test_seeded_deterministic_and_pure():
    rows = make_rows()
    snapshot = json.dumps(rows)
    assert lme.select_subset(rows, seed=7) == lme.select_subset(list(reversed(rows)), seed=7)
    assert lme.select_subset(rows, seed=7) != lme.select_subset(rows, seed=8)
    assert json.dumps(rows) == snapshot


def test_full_context_subset_about_10():
    sel = lme.select_subset(make_rows())
    sub = lme.full_context_subset(sel)
    assert len(sub) == 10
    assert all(sum(lme.ability(r) == a for r in sub) == 2 for a in lme.ABILITIES)
    assert {r["question_id"] for r in sub} <= {r["question_id"] for r in sel}
    assert sub == lme.full_context_subset(list(reversed(sel)))


def test_unknown_question_type_raises_value_error():
    with pytest.raises(ValueError, match="weird-type.*q9"):
        lme.ability({"question_id": "q9", "question_type": "weird-type"})


def test_split_sizes_on_fixture():
    sizes = lme.split_sizes(FIXTURE)
    assert sizes["questions"] == 25
    assert sum(v for k, v in sizes.items() if k != "questions") == 25


def test_download_idempotent_with_injected_fetch(tmp_path):
    calls = []

    def fetch(url, dest):
        calls.append(url)
        dest.write_bytes(FIXTURE.read_bytes())

    cache = tmp_path / "c"
    p = lme.download(cache, fetch=fetch)
    assert p == cache / "longmemeval_s_cleaned.json" and p.exists()
    assert len(calls) == 2 and all("xiaowu0162/longmemeval-cleaned" in u for u in calls)
    lme.download(cache, fetch=fetch)
    assert len(calls) == 2
    assert not list(cache.glob("*.tmp"))


def _good():
    return FIXTURE.read_bytes()


def test_truncated_fetch_then_good_retry(tmp_path):
    calls = []

    def fetch(url, dest):
        calls.append(url)
        dest.write_bytes(_good()[: len(_good()) // 2] if len(calls) == 1 else _good())

    sizes = {n: len(_good()) for n in lme.FILES}
    cache = tmp_path / "c"
    p = lme.download(cache, fetch=fetch, expected_sizes=sizes)
    assert p.read_bytes() == _good()
    assert len(calls) == 3  # first file twice, second once
    assert (cache / (lme.FILES[0] + ".size")).read_text() == str(len(_good()))
    assert not list(cache.glob("*.tmp"))


def test_always_truncated_raises_after_3_attempts(tmp_path):
    calls = []

    def fetch(url, dest):
        calls.append(url)
        dest.write_bytes(_good()[:10])

    cache = tmp_path / "c"
    with pytest.raises(RuntimeError, match="download truncated: got 10 of"):
        lme.download(cache, fetch=fetch, expected_sizes={n: len(_good()) for n in lme.FILES})
    assert len(calls) == 3
    assert not list(cache.glob("*.tmp")) and not (cache / lme.FILES[0]).exists()


def test_existing_truncated_file_without_sidecar_is_refetched(tmp_path):
    cache = tmp_path / "c"
    cache.mkdir()
    (cache / lme.FILES[0]).write_bytes(_good()[:50])
    (cache / lme.FILES[1]).write_bytes(_good())  # healthy: ends with `]`
    calls = []

    def fetch(url, dest):
        calls.append(url)
        dest.write_bytes(_good())

    lme.download(cache, fetch=fetch)
    assert len(calls) == 1 and lme.FILES[0] in calls[0]
    assert (cache / lme.FILES[0]).read_bytes() == _good()


def test_file_with_matching_sidecar_is_skipped_and_mismatch_refetched(tmp_path):
    cache = tmp_path / "c"
    cache.mkdir()
    for n in lme.FILES:
        (cache / n).write_bytes(b"not json at all")  # sidecar wins over the `]` check
        (cache / (n + ".size")).write_text(str(len(b"not json at all")))
    calls = []

    def fetch(url, dest):
        calls.append(url)
        dest.write_bytes(_good())

    lme.download(cache, fetch=fetch)
    assert calls == []
    assert (cache / lme.FILES[0]).read_bytes() == b"not json at all"
    (cache / (lme.FILES[0] + ".size")).write_text("999999")
    lme.download(cache, fetch=fetch)
    assert len(calls) == 1


def test_load_selected_truncated_file_raises_and_keeps_file(tmp_path):
    cache = tmp_path / "c"
    cache.mkdir()
    src = cache / lme.FILES[0]
    src.write_bytes(_good()[:-40])
    with pytest.raises(ValueError, match=r"longmemeval_s_cleaned\.json.*truncated or corrupt.*--download"):
        lme.load_selected(cache)
    assert src.exists()
