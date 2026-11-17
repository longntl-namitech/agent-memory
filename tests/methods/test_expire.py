from datetime import datetime, timedelta

from agent_memory.core.layout import Entry, Store
from agent_memory.methods.expire.stage import EXPIRY_DAYS, Expire

T0 = datetime(2026, 1, 1)


def ent(id, kind="log", exp=None, key=None):
    return Entry(id, kind, key, ["t"], id, 5, T0, T0, exp, "active")


def ids(entries):
    return [e.id for e in entries]


def test_constant():
    assert EXPIRY_DAYS == 7


def test_active_at_6_days(tmp_path):
    s = Store(tmp_path)
    s.add(ent("l"))
    Expire().forget(s, T0 + timedelta(days=6))
    assert ids(s.log()) == ["l"]


def test_active_one_second_before_7_days(tmp_path):
    s = Store(tmp_path)
    s.add(ent("l"))
    Expire().forget(s, T0 + timedelta(days=7) - timedelta(seconds=1))
    assert ids(s.log()) == ["l"]


def test_archived_at_7_days(tmp_path):
    s = Store(tmp_path)
    s.add(ent("l"))
    now = T0 + timedelta(days=7)
    Expire().forget(s, now)
    assert s.log() == []
    [e] = s.all_log()
    assert (e.status, e.archived_at, e.expires_at) == ("archived", now, now)


def test_expiry_assigned_and_persisted(tmp_path):
    s = Store(tmp_path)
    s.add(ent("l"))
    Expire().forget(s, T0 + timedelta(days=2))
    assert Store(tmp_path).log()[0].expires_at == T0 + timedelta(days=7)


def test_rule_never_expired(tmp_path):
    s = Store(tmp_path)
    s.add(ent("r", "rule"))
    Expire().forget(s, T0 + timedelta(days=400))
    assert ids(s.rules()) == ["r"] and s.rules()[0].expires_at is None


def test_fact_without_expiry_untouched_and_explicit_fact_expires(tmp_path):
    s = Store(tmp_path)
    s.add(ent("f1", "fact", key="a"))
    s.add(ent("f2", "fact", key="b", exp=T0 + timedelta(days=1)))
    Expire().forget(s, T0 + timedelta(days=30))
    assert ids(s.facts()) == ["f1"] and s.facts()[0].expires_at is None


def test_explicit_expiry_kept(tmp_path):
    s = Store(tmp_path)
    exp = T0 + timedelta(days=30)
    s.add(ent("l", exp=exp))
    Expire().forget(s, T0 + timedelta(days=10))
    assert s.log()[0].expires_at == exp


def test_idempotent_and_no_write_when_nothing_to_do(tmp_path):
    s = Store(tmp_path)
    s.add(ent("l", exp=T0 + timedelta(days=30)))
    s.add(ent("r", "rule"))
    before = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()}
    now = T0 + timedelta(days=1)
    Expire().forget(s, now)
    assert {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()} == before
    s.add(ent("o"))
    Expire().forget(s, T0 + timedelta(days=8))
    snap = (tmp_path / "log.jsonl").read_text()
    Expire().forget(s, T0 + timedelta(days=8))
    assert (tmp_path / "log.jsonl").read_text() == snap
