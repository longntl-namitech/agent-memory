from datetime import datetime

import pytest

from agent_memory.core import registry
from agent_memory.core.config import Config, ConfigError, build, load_config
from agent_memory.core.layout import Store
from agent_memory.core.llm import Completion
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
    def __init__(self, replies=("out",)):
        self.replies = list(replies)
        self.messages = []

    def chat(self, messages, *, purpose):
        self.messages.append(messages)
        return Completion(self.replies.pop(0) if len(self.replies) > 1 else self.replies[0], 3, 4)


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
    assert result == AgentResult("out", "out", 0, 7, None)


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
