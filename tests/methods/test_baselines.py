from datetime import datetime

import numpy as np

from agent_memory.core.clock import SimClock
from agent_memory.core.config import build, Config
from agent_memory.core.eval.simulation import run_simulation
from agent_memory.core.eval.tasks import generate
from agent_memory.core.layout import Store
from agent_memory.core.llm import Completion, TokenBudget
from agent_memory.core.memory import Event, Task
from agent_memory.methods.full_context.stage import FullContext
from agent_memory.methods.naive_rag.stage import NaiveRag

NOW = datetime(2026, 1, 5, 9)
TASK = Task(id=1, week=1, day=1, lead={"name": "Ann", "company": "Acme", "product": "alpha"}, tags=["acme"],
            wants_log=False)


class FakeEmbedder:
    """Texts map to fixed vectors by their first word; the query 'Ann Acme alpha' maps to the alpha axis."""

    name = "fake"
    VEC = {"alpha": [1, 0, 0], "beta": [0, 1, 0], "gamma": [0, 0, 1], "near": [0.9, 0.1, 0], "Ann": [1, 0, 0]}

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return np.array([self.VEC[t.split()[0]] for t in texts], dtype=float)


class StubLLM:
    def __init__(self):
        self.budget = TokenBudget(None)

    def chat(self, messages, *, purpose):
        self.budget.spend(5)
        return Completion("Hi, 1,200 USD excl. VAT.", 3, 2)


def ev(text):
    return Event("result", text, ["acme"], "task")


def test_full_context_returns_all_events(tmp_path):
    mem = FullContext(Store(tmp_path))
    for i, t in enumerate(["first", "second", "third"]):
        mem.write(ev(t), NOW.replace(hour=9 + i))
    out = mem.recall(TASK, NOW)
    assert out.splitlines() == ["first", "second", "third"]
    assert len(mem.store.log()) == 3 and not mem.store.rules() and not mem.store.facts()


def test_naive_rag_top_k(tmp_path):
    emb = FakeEmbedder()
    mem = NaiveRag(Store(tmp_path), embedder=emb)
    texts = ["beta 1", "alpha 2", "gamma 3", "near 4", "beta 5", "beta 6", "gamma 7"]
    for t in texts:
        mem.write(ev(t), NOW)
    assert len(emb.calls) == len(texts) and all(len(c) == 1 for c in emb.calls)
    out = mem.recall(TASK, NOW).splitlines()
    assert len(out) == 5
    assert out == ["alpha 2", "near 4", "beta 1", "gamma 3", "beta 5"]  # ties keep write order


def test_naive_rag_survives_archive_and_preload(tmp_path):
    store = Store(tmp_path)
    mem = NaiveRag(store, embedder=FakeEmbedder())
    for t in ["beta 1", "alpha 2", "gamma 3"]:
        mem.write(ev(t), NOW)
    store.archive("log-0", NOW)
    assert mem.recall(TASK, NOW).splitlines()[0] == "alpha 2"
    assert mem.recall(TASK, NOW).splitlines() == ["alpha 2", "beta 1", "gamma 3"]
    mem2 = NaiveRag(Store(tmp_path), embedder=FakeEmbedder())  # preloaded store
    mem2.write(ev("near 4"), NOW)
    assert mem2.recall(TASK, NOW) == "near 4"
    ids = [e.id for e in mem2.store._entries["log"]]
    assert len(ids) == len(set(ids))


def test_naive_rag_k_larger_than_history_and_empty(tmp_path):
    mem = NaiveRag(Store(tmp_path), embedder=FakeEmbedder())
    assert mem.recall(TASK, NOW) == ""
    mem.write(ev("alpha 1"), NOW)
    assert mem.recall(TASK, NOW) == "alpha 1"


def test_full_context_ids_unique_after_archive_and_empty(tmp_path):
    store = Store(tmp_path)
    mem = FullContext(store)
    assert mem.recall(TASK, NOW) == ""
    for t in ["a", "b"]:
        mem.write(ev(t), NOW)
    store.archive("log-0", NOW)
    mem.write(ev("c"), NOW)
    assert mem.recall(TASK, NOW).splitlines() == ["b", "c"]
    mem2 = FullContext(Store(tmp_path))
    mem2.write(ev("d"), NOW)
    ids = [e.id for e in mem2.store._entries["log"]]
    assert len(ids) == len(set(ids)) == 4


def test_registered_and_simulation_smoke(tmp_path):
    import agent_memory.methods  # noqa: F401  registers the stages
    tasks = [t for t in generate() if t.week <= 2]
    for name, deps in (("full_context", {}), ("naive_rag", {"embedder": HashEmbedder()})):
        store = Store(tmp_path / name)
        llm = StubLLM()
        agent = build(Config(memory=name), llm=llm, store=store, **deps)
        run_simulation(agent, tasks, SimClock(datetime(2026, 1, 5)), None, store=store)
        assert len(store.log()) >= len(tasks)


class HashEmbedder:
    name = "hash"

    def embed(self, texts):
        return np.array([[len(w) + 1 for w in (t.split() + ["x"] * 3)[:3]] for t in texts], dtype=float)
