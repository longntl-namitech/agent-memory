import json

import pytest
from datetime import datetime

from agent_memory.core.layout import MAX_RULES, Entry, Store
from agent_memory.core.llm import Completion
from agent_memory.core.memory import Event
from agent_memory.methods.write_filter.stage import WriteFilter
from agent_memory.methods.write_raw.stage import WriteRaw

NOW = datetime(2026, 1, 5, 9)


class StubLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def chat(self, messages, *, purpose):
        assert purpose == "write_filter"
        self.prompts.append(messages)
        return Completion(self.replies.pop(0), 1, 1)


def reply(**kw):
    return json.dumps({"kind": "log", "key": "", "tags": [], "importance": 5, "text": "lesson", **kw})


def ev(text="raw transcript line", kind="result", tags=("acme",)):
    return Event(kind, text, list(tags), "task")


def test_lessons_not_transcripts(tmp_path):
    store, e = Store(tmp_path), ev()
    out = WriteFilter().write(e, store, NOW, StubLLM(reply(text="Acme prefers short emails")))
    assert [x.text for x in out] == ["Acme prefers short emails"]
    assert all(x.text != e.text for x in store.log())
    assert store.log()[0].created_at == store.log()[0].last_used_at == NOW


def test_one_llm_call_per_event(tmp_path):
    store, llm = Store(tmp_path), StubLLM(reply(), reply())
    for _ in range(2):
        WriteFilter().write(ev(), store, NOW, llm)
    assert len(llm.prompts) == 2


def test_reuses_existing_key_for_tag(tmp_path):
    store = Store(tmp_path)
    llm = StubLLM(reply(kind="fact", key="Booking Link", text="link A"),
                  reply(kind="fact", key="booking-link", text="link B"))
    WriteFilter().write(ev(), store, NOW, llm)
    WriteFilter().write(ev(), store, NOW, llm)
    assert "booking-link" in llm.prompts[1][-1]["content"]
    assert [(f.key, f.text) for f in store.facts()] == [("booking-link", "link B")]


def test_same_llm_rule_text_twice_one_rule(tmp_path):
    store = Store(tmp_path)
    llm = StubLLM(reply(kind="rule", text="Never  mention PRICE"), reply(kind="rule", text="never mention price"))
    WriteFilter().write(ev("x", "correction", ["global"]), store, NOW, llm)
    assert WriteFilter().write(ev("y", "correction", ["global"]), store, NOW, llm) == []
    assert len(store.rules()) == 1


def test_same_correction_twice_one_llm_call_one_rule(tmp_path):
    store, w = Store(tmp_path), WriteFilter()
    llm = StubLLM(reply(kind="rule", text="Never mention price"), reply(kind="rule", text="Do not quote prices"))
    w.write(ev("Never mention  price", "correction", ["global"]), store, NOW, llm)
    assert w.write(ev("never mention price", "correction", ["global"]), store, NOW, llm) == []
    assert len(llm.prompts) == 1 and len(store.rules()) == 1


def test_reworded_outputs_of_different_corrections_fill_to_cap(tmp_path):
    store, w = Store(tmp_path), WriteFilter()
    llm = StubLLM(*[reply(kind="rule", text=f"Rule wording {i}") for i in range(MAX_RULES + 1)])
    for i in range(MAX_RULES + 1):
        w.write(ev(f"correction {i}", "correction", ["global"]), store, NOW, llm)
    assert len(store.rules()) == MAX_RULES and len(llm.prompts) == MAX_RULES + 1
    assert w.dropped_rules == 1


def test_seen_corrections_do_not_leak_across_instances(tmp_path):
    llm = StubLLM(reply(kind="rule", text="a"), reply(kind="rule", text="a"))
    c = ev("same", "correction", ["global"])
    WriteFilter().write(c, Store(tmp_path / "one"), NOW, llm)
    WriteFilter().write(c, Store(tmp_path / "two"), NOW, llm)
    assert len(llm.prompts) == 2


def test_full_rules_skipped_without_raising(tmp_path):
    store = Store(tmp_path)
    for i in range(MAX_RULES):
        store.add(Entry(f"rule-{i}", "rule", None, [], f"rule {i}", 5, NOW, NOW, None, "active"))
    w = WriteFilter()
    out = w.write(ev("x", "correction"), store, NOW, StubLLM(reply(kind="rule", text="brand new")))
    assert out == [] and len(store.rules()) == MAX_RULES
    assert w.dropped_rules == 1 and WriteFilter().dropped_rules == 0


def test_bad_json_or_kind_falls_back_to_log(tmp_path):
    store, w = Store(tmp_path), WriteFilter()
    llm = StubLLM("not json", reply(kind="bogus"))
    w.write(ev("one"), store, NOW, llm)
    w.write(ev("two"), store, NOW, llm)
    assert [e.text for e in store.log()] == ["one", "two"]
    assert w.fallbacks == 2 and WriteFilter().fallbacks == 0


def test_write_raw_makes_one_log_entry_no_llm(tmp_path):
    store = Store(tmp_path)
    out = WriteRaw().write(ev("hello"), store, NOW, None)
    assert [e.text for e in store.log()] == ["hello"] and len(out) == 1


def test_model_tags_are_ignored(tmp_path):
    store = Store(tmp_path)
    WriteFilter().write(ev(), store, NOW, StubLLM(reply(tags=["invented", "acme-2"])))
    assert store.log()[0].tags == ["acme"]


def test_rule_only_from_correction(tmp_path):
    store = Store(tmp_path)
    WriteFilter().write(ev(kind="result"), store, NOW, StubLLM(reply(kind="rule", text="a lesson")))
    assert store.rules() == [] and [e.text for e in store.log()] == ["a lesson"]
    WriteFilter().write(ev(kind="correction"), store, NOW, StubLLM(reply(kind="rule", text="do x")))
    assert [r.text for r in store.rules()] == ["do x"]


def _c():
    return ev("Never mention price", "correction", ["global"])


@pytest.mark.parametrize("first", ["not json", reply(kind="fact", key="k", text="a fact")])
def test_non_rule_first_outcome_stays_eligible(tmp_path, first):
    store, w = Store(tmp_path), WriteFilter()
    llm = StubLLM(first, reply(kind="rule", text="Never mention price"), reply(kind="rule", text="other"))
    w.write(_c(), store, NOW, llm)
    w.write(_c(), store, NOW, llm)
    assert len(store.rules()) == 1 and len(llm.prompts) == 2
    assert w.write(_c(), store, NOW, llm) == [] and len(llm.prompts) == 2  # rule exists: no third call


def test_duplicate_of_active_rule_marks_seen(tmp_path):
    store, w = Store(tmp_path), WriteFilter()
    store.add(Entry("rule-0", "rule", None, [], "never mention price", 5, NOW, NOW, None, "active"))
    llm = StubLLM(reply(kind="rule", text="Never mention price"), reply(kind="rule", text="x"))
    assert w.write(_c(), store, NOW, llm) == [] and w.write(_c(), store, NOW, llm) == []
    assert len(llm.prompts) == 1


def test_dropped_at_cap_marks_seen(tmp_path):
    store, w = Store(tmp_path), WriteFilter()
    for i in range(MAX_RULES):
        store.add(Entry(f"rule-{i}", "rule", None, [], f"rule {i}", 5, NOW, NOW, None, "active"))
    llm = StubLLM(reply(kind="rule", text="brand new"), reply(kind="rule", text="x"))
    w.write(_c(), store, NOW, llm)
    assert w.write(_c(), store, NOW, llm) == [] and len(llm.prompts) == 1 and w.dropped_rules == 1



@pytest.mark.parametrize("raw,kind,imp", [
    ('```json\n{"kind": "log", "text": "t", "importance": 3}\n```', "log", 3),
    ('Sure! {"kind": "log", "text": "t", "importance": 3} done', "log", 3),
    ('{"kind": "log", "text": "t", "importance": "7"}', "log", 7),
    ('{"kind": "Rule", "text": "t"}', "rule", 5),
    ('{"kind": " FACT ", "key": "k", "text": "t", "importance": "high"}', "fact", 5),
])
def test_parser_tolerates(raw, kind, imp):
    d = WriteFilter._parse(raw)
    assert d["kind"] == kind and d["importance"] == imp
