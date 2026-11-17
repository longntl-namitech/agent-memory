import json
from datetime import datetime

from agent_memory.core.layout import MAX_RULES, Entry, Store
from agent_memory.core.llm import Completion
from agent_memory.core.memory import Event
from agent_memory.methods.write_filter import stage as wf
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


def test_same_correction_twice_one_rule(tmp_path):
    store = Store(tmp_path)
    llm = StubLLM(reply(kind="rule", text="Never  mention PRICE"), reply(kind="rule", text="never mention price"))
    c = ev("x", "correction", ["global"])
    WriteFilter().write(c, store, NOW, llm)
    assert WriteFilter().write(c, store, NOW, llm) == []
    assert len(store.rules()) == 1


def test_full_rules_skipped_without_raising(tmp_path):
    store = Store(tmp_path)
    for i in range(MAX_RULES):
        store.add(Entry(f"rule-{i}", "rule", None, [], f"rule {i}", 5, NOW, NOW, None, "active"))
    out = WriteFilter().write(ev("x", "correction"), store, NOW, StubLLM(reply(kind="rule", text="brand new")))
    assert out == [] and len(store.rules()) == MAX_RULES


def test_bad_json_or_kind_falls_back_to_log(tmp_path):
    store, before = Store(tmp_path), wf.FALLBACKS
    llm = StubLLM("not json", reply(kind="bogus"))
    WriteFilter().write(ev("one"), store, NOW, llm)
    WriteFilter().write(ev("two"), store, NOW, llm)
    assert [e.text for e in store.log()] == ["one", "two"]
    assert wf.FALLBACKS == before + 2


def test_write_raw_makes_one_log_entry_no_llm(tmp_path):
    store = Store(tmp_path)
    out = WriteRaw().write(ev("hello"), store, NOW, None)
    assert [e.text for e in store.log()] == ["hello"] and len(out) == 1
