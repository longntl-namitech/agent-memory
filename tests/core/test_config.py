import json
from datetime import datetime

import pytest

from agent_memory.core import registry
from agent_memory.core.config import Config, ConfigError, build, load_config
from agent_memory.core.layout import Entry, Store
from agent_memory.core.llm import Completion, TokenBudget
from agent_memory.core.memory import AgentResult, Event, MemoryAgent, RetryResult, Task

NOW = datetime(2026, 1, 5, 9)
TASK = Task(id=1, week=1, day=1, lead={"name": "Ann"}, tags=["lead"], wants_log=False)


@pytest.fixture(autouse=True)
def clean_registry():
    saved = dict(registry._REGISTRY)
    registry._REGISTRY.clear()
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)


class FakeLLM:
    """Mirrors LLMClient: a repeat of the same messages is a cache hit and costs the budget 0."""

    def __init__(self, replies=("out",)):
        self.replies = list(replies)
        self.budget = TokenBudget(None)
        self.cache = {}

    def chat(self, messages, *, purpose):
        key = json.dumps(messages, sort_keys=True)
        if key not in self.cache:
            self.cache[key] = Completion(self.replies.pop(0) if len(self.replies) > 1 else self.replies[0], 3, 4)
            self.budget.spend(7)
        return self.cache[key]


def fake_stages():
    calls = []

    @registry.register("write_raw", "write")
    class Write:
        def write(self, event, store, now, llm):
            calls.append(("write", event.text))
            return []

    @registry.register("pool_route", "sort")
    class Route:
        pass

    @registry.register("rules_only", "recall")
    class Recall:
        def recall(self, task, store, now, route):
            calls.append(("recall", type(route).__name__))
            return "ctx"

    @registry.register("expire", "forget")
    class Expire:
        def forget(self, store, now):
            calls.append(("forget", now))

    return calls


def toml(tmp_path, text):
    p = tmp_path / "c.toml"
    p.write_text(text)
    return p


def test_unknown_stage_fails_fast(tmp_path):
    fake_stages()
    with pytest.raises(ConfigError, match="nope"):
        load_config(toml(tmp_path, 'name = "x"\n[write]\nstage = "nope"\n'))
    with pytest.raises(ConfigError, match="nope"):
        load_config(toml(tmp_path, '[forget]\nstages = ["expire", "nope"]\n'))


def test_baseline_config_names_whole_memory(tmp_path):
    @registry.register("naive_rag", "memory")
    class Naive:
        def __init__(self, store, llm):
            self.store = store

        def write(self, event, now): ...
        def recall(self, task, now): return "naive"
        def reflect(self, now): ...
        def forget(self, now): ...

    cfg = load_config(toml(tmp_path, 'name = "baseline_naive_rag"\nmemory = "naive_rag"\n'))
    assert cfg.memory == "naive_rag" and cfg.name == "baseline_naive_rag"
    agent = build(cfg, llm=FakeLLM(), store=Store(tmp_path / "s"))
    assert isinstance(agent, MemoryAgent) and isinstance(agent.memory, Naive)


def test_agent_config(tmp_path):
    @registry.register("hermes", "agent")
    class Hermes:
        def __init__(self, config, llm, store):
            self.config = config

        def run_task(self, task, now):
            return AgentResult("o", "o", 0, 0, None)

    cfg = load_config(toml(tmp_path, 'agent = "hermes"\n[hermes]\nmodel = "m"\n'))
    assert cfg.agent == "hermes" and cfg.options == {"hermes": {"model": "m"}}
    agent = build(cfg, llm=FakeLLM(), store=Store(tmp_path / "s"))
    assert isinstance(agent, Hermes) and agent.config is cfg


def test_default_stand_ins(tmp_path):
    cfg = load_config(toml(tmp_path, 'name = "bare"\n'))
    assert cfg == Config(name="bare", write="write_raw", sort="pool_route", recall="rules_only")
    assert cfg.reflect == [] and cfg.forget == [] and cfg.agent is None and cfg.memory is None
    # Stand-ins are looked up at build time, so a missing one fails there by name.
    with pytest.raises(ConfigError, match="write_raw"):
        build(cfg, llm=FakeLLM(), store=Store(tmp_path / "s"))
    calls = fake_stages()
    agent = build(cfg, llm=FakeLLM(), store=Store(tmp_path / "s"))
    agent.memory.write(Event("email", "hi", [], "inbox"), NOW)
    result = agent.run_task(TASK, NOW)
    agent.memory.forget(NOW)
    assert calls == [("write", "hi"), ("recall", "Route")]
    assert (result.output, result.first_output, result.retries, result.failed_check) == ("out", "out", 0, None)


def entry(text):
    return Entry(id=text, kind="log", key=None, tags=[], text=text, importance=1,
                 created_at=NOW, last_used_at=NOW, expires_at=None, status="active")


def test_write_stage_persists_its_own_entries(tmp_path):
    fake_stages()

    @registry.register("persisting", "write")
    class Persisting:
        def write(self, event, store, now, llm):
            e = entry(event.text)
            store.add(e)
            return [e]  # informational only

    cfg = load_config(toml(tmp_path, '[write]\nstage = "persisting"\n'))
    store = Store(tmp_path / "s")
    build(cfg, llm=FakeLLM(), store=store).memory.write(Event("email", "hi", [], "inbox"), NOW)
    assert [e.text for e in store.log()] == ["hi"]  # StagedMemory added no duplicate


def test_tokens_are_budget_delta(tmp_path):
    fake_stages()

    @registry.register("llm_write", "write")
    class LLMWrite:  # stands in for write_filter: an LLM call inside memory
        def write(self, event, store, now, llm):
            llm.chat([{"role": "user", "content": event.text}], purpose="write")
            return []

    @registry.register("reflexion", "retry")
    class Reflexion:
        def retry(self, task, first_output, failed_check, context, llm):
            return RetryResult(llm.chat([], purpose="retry").text, "note")

    cfg = load_config(toml(tmp_path, '[write]\nstage = "llm_write"\n[reflect]\nstages = ["reflexion"]\n'))
    llm = FakeLLM(["bad", "good", "ok"])
    agent = build(cfg, llm=llm, store=Store(tmp_path / "s"), check=lambda t, out: None if out == "good" else "x")
    # task call + retry call + write-stage call on the retry note, 7 each
    assert agent.run_task(TASK, NOW).tokens == 21 == llm.budget.used
    assert agent.run_task(TASK, NOW).tokens == 0  # every call is a cache hit


def test_retry_runs_on_failed_check(tmp_path):
    calls = fake_stages()

    @registry.register("reflexion", "retry")
    class Reflexion:
        def retry(self, task, first_output, failed_check, context, llm):
            return RetryResult(llm.chat([], purpose="retry").text, f"note: {failed_check}")

    cfg = load_config(toml(tmp_path, '[reflect]\nstages = ["reflexion"]\n[forget]\nstages = ["expire"]\n'))
    agent = build(cfg, llm=FakeLLM(["bad", "good"]), store=Store(tmp_path / "s"),
                  check=lambda task, out: None if out == "good" else "missing name")
    result = agent.run_task(TASK, NOW)
    assert result == AgentResult("good", "bad", 1, 14, None)
    assert ("write", "note: missing name") in calls  # the reflection note goes to memory
    agent.memory.forget(NOW)
    assert ("forget", NOW) in calls
