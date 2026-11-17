import json
from datetime import datetime

import pytest

from agent_memory.core.layout import MAX_RULES, Entry, Store
from agent_memory.core.llm import BudgetExceeded, Completion
from agent_memory.methods.reflect.stage import MAX_NEW_RULES, Reflect

NOW = datetime(2026, 1, 9, 17)
OLD = datetime(2026, 1, 1)


class StubLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def chat(self, messages, *, purpose):
        assert purpose == "reflect"
        self.prompts.append(messages)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return Completion(r, 1, 1)


def entry(id_, kind, text, imp=5, last=OLD):
    return Entry(id_, kind, None, ["global"], text, imp, OLD, last, None, "active")


def rules_reply(*rules):
    return json.dumps({"rules": list(rules)})


def rule(text, sources=(), importance=5):
    return {"text": text, "importance": importance, "sources": list(sources)}


def store_with_logs(tmp_path, n=3):
    s = Store(tmp_path)
    for i in range(n):
        s.add(entry(f"log-{i}", "log", f"line {i}"))
    return s


def test_at_most_3_rules(tmp_path):
    s = store_with_logs(tmp_path)
    Reflect().reflect(s, NOW, StubLLM(rules_reply(*[rule(f"rule {i}") for i in range(5)])))
    assert MAX_NEW_RULES == 3
    assert [r.text for r in s.rules()] == ["rule 0", "rule 1", "rule 2"]
    r = s.rules()[0]
    assert (r.kind, r.tags, r.created_at, r.last_used_at) == ("rule", ["global"], NOW, NOW)


def test_source_log_lines_archived(tmp_path):
    s = store_with_logs(tmp_path)
    Reflect().reflect(s, NOW, StubLLM(rules_reply(rule("r", ["log-0", "log-2", "nope", "rule-9"]))))
    assert [e.id for e in s.log()] == ["log-1"]
    assert all(e.archived_at == NOW for e in s.all_log() if e.status == "archived")


def test_rules_full_archives_first(tmp_path):
    s = store_with_logs(tmp_path, 1)
    for i in range(MAX_RULES):
        s.add(entry(f"rule-{i}", "rule", f"old {i}", imp=5 + (i % 3), last=datetime(2026, 1, 2 + i % 5)))
    llm = StubLLM(rules_reply(rule("new one", ["log-0"], 9)))
    Reflect().reflect(s, NOW, llm)
    assert len(s.rules()) == MAX_RULES
    assert "new one" in [r.text for r in s.rules()]
    gone = [r for r in s.all_rules() if r.status == "archived"]
    assert len(gone) == 1 and gone[0].importance == 5 and gone[0].last_used_at == datetime(2026, 1, 2)
    assert gone[0].archived_at == NOW


def test_full_with_three_never_evicts_new(tmp_path):
    s = store_with_logs(tmp_path, 1)
    for i in range(MAX_RULES):
        s.add(entry(f"rule-{i}", "rule", f"old {i}", imp=9))
    Reflect().reflect(s, NOW, StubLLM(rules_reply(*[rule(f"n{i}", [], 1) for i in range(3)])))
    texts = [r.text for r in s.rules()]
    assert len(texts) == MAX_RULES and {"n0", "n1", "n2"} <= set(texts)


def test_duplicate_skipped(tmp_path):
    s = store_with_logs(tmp_path)
    s.add(entry("rule-0", "rule", "Never  mention PRICE"))
    Reflect().reflect(s, NOW, StubLLM(rules_reply(rule("never mention price", ["log-0"]), rule("fresh", ["log-1"]))))
    assert [r.text for r in s.rules()] == ["Never  mention PRICE", "fresh"]
    assert [e.id for e in s.log()] == ["log-2"]  # pure duplicate's sources are archived too


def test_no_log_no_call(tmp_path):
    llm = StubLLM()
    Reflect().reflect(Store(tmp_path), NOW, llm)
    assert llm.prompts == []


@pytest.mark.parametrize("bad", ["not json", "[1]", '{"rules": 5}'])
def test_bad_reply_does_nothing(tmp_path, bad):
    s = store_with_logs(tmp_path)
    r = Reflect()
    r.reflect(s, NOW, StubLLM(bad))
    assert s.rules() == [] and len(s.log()) == 3 and r.failures == 1


def test_failures_counter_per_instance(tmp_path):
    s = store_with_logs(tmp_path)
    a, b = Reflect(), Reflect()
    a.reflect(s, NOW, StubLLM("garbage"))
    assert (a.failures, b.failures) == (1, 0)


def test_fenced_json_and_importance_clamp(tmp_path):
    s = store_with_logs(tmp_path)
    Reflect().reflect(s, NOW, StubLLM("```json\n" + rules_reply(rule("a", [], 99), {"text": "b", "importance": "x"}) + "\n```"))
    assert [(r.text, r.importance) for r in s.rules()] == [("a", 10), ("b", 5)]


def test_budget_exceeded_propagates(tmp_path):
    with pytest.raises(BudgetExceeded):
        Reflect().reflect(store_with_logs(tmp_path), NOW, StubLLM(BudgetExceeded("x")))


def test_bad_items_skipped_not_failure(tmp_path):
    s = store_with_logs(tmp_path)
    r = Reflect()
    r.reflect(s, NOW, StubLLM('{"rules": [1, {"text": ""}, {"nope": 1}, {"text": "ok", "sources": "log-0"}]}'))
    assert [x.text for x in s.rules()] == ["ok"] and r.failures == 0 and len(s.log()) == 3
