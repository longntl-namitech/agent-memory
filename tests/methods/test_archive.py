from datetime import datetime, timedelta

from agent_memory.core.layout import Entry, Store
from agent_memory.methods.archive.stage import ARCHIVE_AFTER_DAYS, Archive
from agent_memory.methods.coala_stores.stage import CoalaStores
from agent_memory.methods.tag_recall.stage import TagRecall
from agent_memory.core.memory import Task

NOW = datetime(2026, 3, 1)


def ent(id, kind="rule", used=NOW):
    return Entry(id, kind, id if kind == "fact" else None, ["t"], id, 5, used, used, None, "active")


def ids(entries):
    return [e.id for e in entries]


def test_constant():
    assert ARCHIVE_AFTER_DAYS == 30


def test_rule_used_29_days_ago_stays(tmp_path):
    s = Store(tmp_path)
    s.add(ent("r", used=NOW - timedelta(days=29)))
    Archive().forget(s, NOW)
    assert ids(s.rules()) == ["r"]


def test_rule_unused_30_days_archived(tmp_path):
    s = Store(tmp_path)
    s.add(ent("r", used=NOW - timedelta(days=30)))
    Archive().forget(s, NOW)
    assert s.rules() == [] and ids(s.all_rules()) == ["r"]


def test_facts_and_log_untouched(tmp_path):
    s = Store(tmp_path)
    old = NOW - timedelta(days=90)
    s.add(ent("f", "fact", old))
    s.add(ent("l", "log", old))
    Archive().forget(s, NOW)
    assert ids(s.facts()) == ["f"] and ids(s.log()) == ["l"]


def test_idempotent_and_no_write_when_nothing(tmp_path):
    s = Store(tmp_path)
    s.add(ent("r", used=NOW - timedelta(days=31)))
    Archive().forget(s, NOW)
    snap = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    mt = {p: p.stat().st_mtime_ns for p in snap}
    Archive().forget(s, NOW)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == snap
    assert {p: p.stat().st_mtime_ns for p in snap} == mt


def test_use_resets_clock(tmp_path):
    s = Store(tmp_path)
    s.add(ent("r", used=NOW - timedelta(days=29)))
    TagRecall().recall(Task(id=1, week=1, day=1, lead={}, tags=[], wants_log=False), s, NOW, CoalaStores())
    Archive().forget(s, NOW + timedelta(days=2))
    assert ids(s.rules()) == ["r"]
