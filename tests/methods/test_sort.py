from datetime import datetime

from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Routed, Task
from agent_memory.methods.coala_stores.stage import CoalaStores
from agent_memory.methods.pool_route.stage import PoolRoute

NOW = datetime(2026, 1, 5, 9)


def e(id, kind, tags=(), status="active"):
    return Entry(id=id, kind=kind, key=id if kind == "fact" else None, tags=list(tags), text=id, importance=5,
                 created_at=NOW, last_used_at=NOW, expires_at=None, status=status)


def task(tags, wants_log=False):
    return Task(id=1, week=1, day=1, lead={}, tags=tags, wants_log=wants_log)


def store(tmp_path, *entries):
    s = Store(tmp_path)
    for x in entries:
        s.add(x)
    return s


def ids(es):
    return [x.id for x in es]


def test_rules_always_facts_by_tag_log_on_request(tmp_path):
    s = store(tmp_path, e("r1", "rule"), e("f-acme", "fact", ["acme"]), e("l1", "log", ["acme"]))
    r = CoalaStores()(s, task(["acme"]))
    assert isinstance(r, Routed)
    assert (ids(r.rules), ids(r.facts), r.log) == (["r1"], ["f-acme"], [])
    assert ids(CoalaStores()(s, task(["acme"], wants_log=True)).log) == ["l1"]


def test_non_matching_tag_excluded_global_included_deduped(tmp_path):
    s = store(tmp_path, e("fa", "fact", ["acme", "x"]), e("fb", "fact", ["beta"]), e("fg", "fact", ["global"]))
    assert ids(CoalaStores()(s, task(["acme", "x"])).facts) == ["fa", "fg"]


def test_archived_never_routed(tmp_path):
    s = store(tmp_path, e("r1", "rule", status="archived"), e("f1", "fact", ["acme"], "archived"),
              e("l1", "log", status="archived"))
    for route in (CoalaStores(), PoolRoute()):
        r = route(s, task(["acme"], wants_log=True))
        assert not (r.rules or r.facts or r.log)


def test_pool_route_ignores_kind(tmp_path):
    s = store(tmp_path, e("r1", "rule"), e("f1", "fact", ["zzz"]), e("l1", "log"))
    r = PoolRoute()(s, task(["acme"]))
    assert sorted(ids(r.facts)) == ["f1", "l1", "r1"] and r.rules == [] and r.log == []
