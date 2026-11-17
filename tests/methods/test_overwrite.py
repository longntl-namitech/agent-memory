from datetime import datetime, timedelta

from agent_memory.core.layout import Entry, Store
from agent_memory.methods.overwrite.stage import Overwrite

T0 = datetime(2026, 1, 1)
NOW = datetime(2026, 2, 1)


def fact(id, key, text, day=0, tags=("t",), imp=5, exp=None):
    t = T0 + timedelta(days=day)
    return Entry(id, "fact", key, list(tags), text, imp, t, t, exp, "active")


def texts(store):
    return [e.text for e in store.facts()]


def test_new_fact_replaces_in_place(tmp_path):
    s = Store(tmp_path)
    s.add(fact("a", "link", "old", 0))
    s.add(fact("b", "link", "new", 1, tags=("n",), imp=8, exp=NOW))
    Overwrite().forget(s, NOW)
    [e] = s.facts()
    assert (e.id, e.created_at, e.text, e.tags, e.importance, e.expires_at, e.last_used_at) == (
        "a", T0, "new", ["n"], 8, NOW, NOW)
    assert "old" not in texts(s)


def test_overwrite_after_slug_normalisation(tmp_path):
    s = Store(tmp_path)
    s.add(fact("a", "Booking Link", "old", 0))
    s.add(fact("b", "booking-link", "new", 1))
    Overwrite().forget(s, NOW)
    assert texts(s) == ["new"]


def test_order_by_created_at_then_store_order(tmp_path):
    s = Store(tmp_path)
    s.add(fact("c", "k", "newest", 2))
    s.add(fact("a", "k", "oldest", 0))
    s.add(fact("b", "k", "mid-1", 1))
    s.add(fact("d", "k", "mid-2", 1))
    Overwrite().forget(s, NOW)
    [e] = s.facts()
    assert (e.id, e.text) == ("a", "newest")
    s2 = Store(tmp_path / "tie")
    s2.add(fact("x", "k", "first", 1))
    s2.add(fact("y", "k", "second", 1))
    Overwrite().forget(s2, NOW)
    assert texts(s2) == ["second"]


def test_archives_losers_with_now_and_ignores_others(tmp_path):
    s = Store(tmp_path)
    s.add(fact("a", "k", "old", 0))
    s.add(fact("b", "k", "new", 1))
    s.add(fact("c", "solo", "alone", 0))
    s.add(Entry("n1", "fact", None, [], "nokey1", 5, T0, T0, None, "active"))
    s.add(Entry("n2", "fact", None, [], "nokey2", 5, T0, T0, None, "active"))
    s.add(Entry("r", "rule", "k", [], "rule", 5, T0, T0, None, "active"))
    s.add(Entry("l", "log", "k", [], "log", 5, T0, T0, None, "active"))
    s.add(fact("z", "gone", "archived", 5))
    s.archive("z", T0)
    Overwrite().forget(s, NOW)
    b = [e for e in s._entries["fact"] if e.id == "b"][0]
    assert (b.status, b.archived_at) == ("archived", NOW)
    solo = [e for e in s.facts() if e.id == "c"][0]
    assert solo.last_used_at == T0
    assert sorted(texts(s)) == ["alone", "new", "nokey1", "nokey2"]
    assert len(s.rules()) == 1 and len(s.log()) == 1


def test_idempotent(tmp_path):
    s = Store(tmp_path)
    s.add(fact("a", "k", "old", 0))
    s.add(fact("b", "k", "new", 1))
    Overwrite().forget(s, NOW)
    before = (tmp_path / "facts.jsonl").read_text()
    Overwrite().forget(s, NOW + timedelta(days=9))
    assert (tmp_path / "facts.jsonl").read_text() == before
