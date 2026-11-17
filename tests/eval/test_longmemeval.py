import json
from pathlib import Path

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
    sub = lme.full_context_subset(lme.select_subset(make_rows()))
    assert len(sub) == 10
    assert all(sum(lme.ability(r) == a for r in sub) == 2 for a in lme.ABILITIES)


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
