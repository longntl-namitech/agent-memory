from datetime import datetime, timedelta

from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Task
from agent_memory.methods.coala_stores.stage import CoalaStores
from agent_memory.methods.pool_route.stage import PoolRoute
from agent_memory.methods.rules_only.stage import RulesOnly
from agent_memory.methods.tag_recall.stage import TagRecall

NOW = datetime(2026, 1, 5, 9)
LATER = NOW + timedelta(days=3)


def e(id, kind, tags=(), text=None):
    return Entry(id=id, kind=kind, key=id if kind == "fact" else None, tags=list(tags), text=text or f"text-{id}",
                 importance=5, created_at=NOW, last_used_at=NOW, expires_at=None, status="active")


def task(tags, wants_log=False):
    return Task(id=1, week=1, day=1, lead={}, tags=tags, wants_log=wants_log)


def store(tmp_path):
    s = Store(tmp_path)
    for x in (e("r1", "rule"), e("r2", "rule"), e("fa", "fact", ["acme"]), e("fb", "fact", ["beta"]),
              e("fg", "fact", ["global"]), e("l1", "log", ["acme"])):
        s.add(x)
    return s


def test_rules_plus_matching_tag_facts(tmp_path):
    out = TagRecall().recall(task(["acme"]), store(tmp_path), LATER, CoalaStores())
    assert out == "## RULES\ntext-r1\ntext-r2\n\n## FACTS\nfa: text-fa\nfg: text-fg"


def test_log_only_when_task_wants_log(tmp_path):
    s = store(tmp_path)
    assert "LOG" not in TagRecall().recall(task(["acme"]), s, LATER, CoalaStores())
    out = TagRecall().recall(task(["acme"], wants_log=True), s, LATER, CoalaStores())
    assert out.endswith("## LOG\ntext-l1")


def test_pool_route_renders_each_entry_by_kind(tmp_path):
    out = TagRecall().recall(task(["acme"]), store(tmp_path), LATER, PoolRoute())
    assert out == ("## RULES\ntext-r1\ntext-r2\n\n## FACTS\nfa: text-fa\nfb: text-fb\nfg: text-fg\n\n"
                   "## LOG\ntext-l1")


def test_rules_only_ignores_route_facts_and_log(tmp_path):
    s = store(tmp_path)
    out = RulesOnly().recall(task(["acme"], wants_log=True), s, LATER, PoolRoute())
    assert out == "## RULES\ntext-r1\ntext-r2"


def test_recall_marks_rendered_entries_only(tmp_path):
    s = store(tmp_path)
    TagRecall().recall(task(["acme"]), s, LATER, CoalaStores())
    used = {x.id for x in (*s.rules(), *s.facts(), *s.log()) if x.last_used_at == LATER}
    assert used == {"r1", "r2", "fa", "fg"}
    s2 = store(tmp_path / "b")
    RulesOnly().recall(task(["acme"]), s2, LATER, CoalaStores())
    assert {x.id for x in (*s2.rules(), *s2.facts(), *s2.log()) if x.last_used_at == LATER} == {"r1", "r2"}


def test_deterministic(tmp_path):
    s = store(tmp_path)
    a = TagRecall().recall(task(["acme"], True), s, LATER, CoalaStores())
    assert a == TagRecall().recall(task(["acme"], True), s, NOW, CoalaStores())
