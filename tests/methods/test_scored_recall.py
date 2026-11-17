from datetime import datetime, timedelta

import numpy as np
import pytest

from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Routed, Task
from agent_memory.methods.scored_recall.stage import DECAY, TOP_K, ScoredRecall, score

NOW = datetime(2026, 1, 5, 9)


def e(id, kind="fact", hours=0.0, imp=5, text=None):
    return Entry(id=id, kind=kind, key=id if kind == "fact" else None, tags=[], text=text or f"text-{id}",
                 importance=imp, created_at=NOW, last_used_at=NOW - timedelta(hours=hours), expires_at=None,
                 status="active")


class Fake:
    """Query is [1, 0]; entry text 'cos=<c>' embeds to a unit vector with cosine c to it."""
    name = "fake"

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        out = []
        for t in texts:
            c = float(t.split("cos=")[1].split()[0]) if "cos=" in t else 1.0
            out.append([c, (1 - c * c) ** 0.5])
        return np.array(out)


def task():
    return Task(id=1, week=1, day=1, lead={"name": "Ann"}, tags=["acme"], wants_log=False)


def run(tmp_path, entries, emb=None):
    s = Store(tmp_path)
    for x in entries:
        s.add(x)
    emb = emb or Fake()
    r = Routed(rules=[x for x in entries if x.kind == "rule"], facts=[x for x in entries if x.kind == "fact"],
               log=[x for x in entries if x.kind == "log"])
    return ScoredRecall(embedder=emb).recall(task(), s, NOW, lambda st, t: r), s, emb


def test_score_formula():
    q = np.array([1.0, 0.0])
    v = np.array([0.6, 0.8])  # cosine 0.6
    assert score(e("a", hours=10, imp=8), q, v, NOW) == pytest.approx(DECAY ** 10 + 0.8 + 0.6)
    assert DECAY == 0.995
    assert score(e("a", hours=0, imp=10), q, v, NOW) == pytest.approx(1 + 1 + 0.6)
    future = e("a", hours=-5, imp=10)  # last used after now: age floors at 0
    assert score(future, q, v, NOW) == pytest.approx(2.6)


def test_order_by_score(tmp_path):
    # a: 0.995^0 + 0.5 + 0.2 = 1.7 ; b: 1 + 0.1 + 0.9 = 2.0 ; c: 1 + 0.9 + 0.5 = 2.4
    out, _, _ = run(tmp_path, [e("a", imp=5, text="cos=0.2"), e("b", imp=1, text="cos=0.9"), e("c", imp=9, text="cos=0.5")])
    assert out == "## FACTS\nc: cos=0.5\nb: cos=0.9\na: cos=0.2"


def test_recent_beats_old_at_equal_relevance(tmp_path):
    out, _, _ = run(tmp_path, [e("old", hours=500, text="cos=0.5 old"), e("new", hours=1, text="cos=0.5 new")])
    assert out.index("new:") < out.index("old:")


def test_top_k_cut_keeps_rules_and_touches(tmp_path):
    facts = [e(f"f{i}", imp=1 + i % 10, text="cos=0.5") for i in range(TOP_K + 4)]
    rule = e("r", "rule", hours=9000, imp=1, text="cos=0.0")
    out, s, _ = run(tmp_path, [rule, *facts])
    assert "cos=0.0" in out
    assert sum(1 for ln in out.splitlines() if ln.startswith("f")) == TOP_K
    assert s.rules()[0].last_used_at == NOW


def test_batched_embedding_and_cache(tmp_path):
    s = Store(tmp_path)
    es = [e("a", text="cos=0.1"), e("b", text="cos=0.2")]
    for x in es:
        s.add(x)
    emb = Fake()
    st = ScoredRecall(embedder=emb)
    route = lambda store, t: Routed(rules=[], facts=es, log=[])
    st.recall(task(), s, NOW, route)
    st.recall(task(), s, NOW, route)
    assert len(emb.calls) == 2
    assert len(emb.calls[0]) == 3  # both entries plus the query, one call
    assert len(emb.calls[1]) == 1  # second recall: query only


def test_importance_clamped():
    q, v = np.array([1.0, 0.0]), np.array([1.0, 0.0])
    assert score(e("a", imp=50), q, v, NOW) == pytest.approx(3.0)
    assert score(e("a", imp=-3), q, v, NOW) == pytest.approx(2.1)


def test_embedder_property_injects(tmp_path, monkeypatch):
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    s = Store(tmp_path)
    x = e("a", text="cos=0.5 alpha")
    s.add(x)
    emb = Fake()
    st = ScoredRecall()
    assert st.embedder is None
    st.embedder = emb
    assert st.embedder is emb
    out = st.recall(task(), s, NOW, lambda store, t: Routed(rules=[], facts=[x], log=[]))
    assert emb.calls
    assert "cos=0.5 alpha" in out


def test_embedder_swap_clears_cached_vectors(tmp_path):
    s = Store(tmp_path)
    x = e("a", text="cos=0.5 alpha")
    s.add(x)
    route = lambda store, t: Routed(rules=[], facts=[x], log=[])
    a, b = Fake(), Fake()
    st = ScoredRecall(embedder=a)
    st.recall(task(), s, NOW, route)
    calls_a = len(a.calls)
    st.embedder = b
    st.recall(task(), s, NOW, route)
    assert len(a.calls) == calls_a
    assert any("cos=0.5 alpha" in t for call in b.calls for t in call)
