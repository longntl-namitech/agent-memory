import json
from datetime import datetime

import pytest

from agent_memory import cli
from agent_memory.core.config import build, load_config
from agent_memory.core.layout import MAX_RULES, Entry, Store
from agent_memory.core.llm import Completion
from agent_memory.core.memory import Event, Task

NOW = datetime(2026, 1, 5, 9)
DEMO = cli.CONFIGS / "demo"


class StubLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def chat(self, messages, *, purpose):
        assert purpose == "assistant_write"
        self.prompts.append(messages[-1]["content"])
        return Completion(self.replies.pop(0), 1, 1)


def reply(*entries):
    return json.dumps({"entries": [{"importance": 5, "key": "", **e} for e in entries]})


def ev(text="My name is Lan and I live in Hanoi."):
    return Event("chat", text, [], "user")


@pytest.fixture
def stages():
    from agent_memory.demo import stages
    return stages


def test_no_memory_is_inert(tmp_path, stages):
    store = Store(tmp_path)
    m = stages.NoMemory(store=store, llm=None, embedder=None)
    m.write(ev(), NOW)
    m.reflect(NOW)
    m.forget(NOW)
    assert m.recall(Task(0, 1, 1, {}, [], False), NOW) == ""
    assert store.rules() == store.facts() == store.all_log() == []


def test_configs_load_and_build(tmp_path, stages):
    from agent_memory.methods.scored_recall.stage import ScoredRecall
    full = load_config(DEMO / "demo_full.toml")
    assert full.name == "demo_full"
    mem = build(full, llm=StubLLM(), store=Store(tmp_path / "f")).memory
    assert isinstance(mem.writer, stages.AssistantWrite) and isinstance(mem.recaller, ScoredRecall)
    assert [type(s).__name__ for s in mem.forgetters] == ["Overwrite", "Expire"]
    assert [type(s).__name__ for s in mem.reflectors] == ["Reflect"]
    none = load_config(DEMO / "demo_no_memory.toml")
    assert none.name == "demo_no_memory"
    assert isinstance(build(none, llm=StubLLM(), store=Store(tmp_path / "n")).memory, stages.NoMemory)


def test_multi_entry_write(tmp_path, stages):
    store, w = Store(tmp_path), stages.AssistantWrite()
    llm = StubLLM(reply({"kind": "fact", "key": "name", "text": "The user is called Lan"},
                        {"kind": "fact", "key": "city", "text": "The user lives in Hanoi"},
                        {"kind": "log", "text": "Lan is on a diet this week"}))
    out = w.write(ev(), store, NOW, llm)
    assert len(out) == 3 and all(e.tags == ["global"] for e in out)
    assert {f.key for f in store.facts()} == {"name", "city"} and len(store.log()) == 1
    assert all(e.created_at == e.last_used_at == NOW and e.expires_at is None for e in out)
    assert "reminder" in llm.prompts[0].lower() and "(none)" in llm.prompts[0]


def test_same_key_overwrites_in_place(tmp_path, stages):
    store, w = Store(tmp_path), stages.AssistantWrite()
    w.write(ev(), store, NOW, StubLLM(reply({"kind": "fact", "key": "city", "text": "Lives in Hanoi"})))
    first = store.facts()[0].id
    llm = StubLLM(reply({"kind": "fact", "key": "City", "text": "Lives in Da Nang"}))
    w.write(ev("I moved to Da Nang"), store, NOW, llm)
    assert [(f.id, f.text) for f in store.facts()] == [(first, "Lives in Da Nang")]
    assert "city" in llm.prompts[0]  # existing keys are shown to the model


def test_invalid_json_falls_back_to_log(tmp_path, stages):
    store, w = Store(tmp_path), stages.AssistantWrite()
    out = w.write(ev("raw text"), store, NOW, StubLLM("not json at all"))
    assert w.fallbacks == 1 and [e.text for e in out] == ["raw text"] and len(store.log()) == 1
    assert out[0].kind == "log" and out[0].tags == ["global"]


def test_rule_cap_not_exceeded(tmp_path, stages):
    store, w = Store(tmp_path), stages.AssistantWrite()
    for i in range(MAX_RULES):
        store.add(Entry(f"rule-{i}", "rule", None, ["global"], f"rule {i}", 5, NOW, NOW, None, "active"))
    out = w.write(ev(), store, NOW, StubLLM(reply({"kind": "rule", "text": "Always answer in Vietnamese"})))
    assert out == [] and w.dropped_rules == 1 and len(store.rules()) == MAX_RULES


def test_rule_deduped(tmp_path, stages):
    store, w = Store(tmp_path), stages.AssistantWrite()
    r = reply({"kind": "rule", "text": "Keep answers short"})
    w.write(ev(), store, NOW, StubLLM(r))
    w.write(ev(), store, NOW, StubLLM(reply({"kind": "rule", "text": "keep  answers SHORT"})))
    assert [x.id for x in store.rules()] == ["rule-0"]


def test_fact_without_key_becomes_log(tmp_path, stages):
    store, w = Store(tmp_path), stages.AssistantWrite()
    out = w.write(ev(), store, NOW, StubLLM(reply({"kind": "fact", "key": "!!", "text": "Likes tea"})))
    assert store.facts() == [] and [e.kind for e in out] == ["log"] and store.log()[0].id == "log-0"


def test_max_six_entries(tmp_path, stages):
    store, w = Store(tmp_path), stages.AssistantWrite()
    out = w.write(ev(), store, NOW, StubLLM(reply(*[{"kind": "log", "text": f"line {i}"} for i in range(9)])))
    assert len(out) == 6 and len(store.log()) == 6


def test_lab_config_tests_unaffected():
    stems = [p.stem for p in cli.CONFIGS.glob("*.toml")]
    assert not any(s.startswith("demo") for s in stems)
    assert {p.stem for p in DEMO.glob("*.toml")} == {"demo_full", "demo_no_memory"}
