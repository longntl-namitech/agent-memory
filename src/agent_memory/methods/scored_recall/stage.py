import os
from datetime import datetime

import numpy as np

from agent_memory.core.embed import Embedder, FastembedEmbedder, OpenAICompatEmbedder
from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Route, Task
from agent_memory.core.registry import register
from agent_memory.methods.tag_recall.stage import render

DECAY = 0.995  # per simulated hour: half-life about 138 h (~6 days)
TOP_K = 8  # non-rule entries kept; rules are always kept


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    n = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / n) if n else 0.0


def score(entry: Entry, query_vec: np.ndarray, entry_vec: np.ndarray, now: datetime) -> float:
    """recency + importance + relevance, equal weights."""
    hours = max((now - entry.last_used_at).total_seconds() / 3600, 0.0)
    return DECAY**hours + min(max(entry.importance, 1), 10) / 10 + _cos(query_vec, entry_vec)


def _default_embedder() -> Embedder:
    if os.environ.get("EMBEDDING_BASE_URL") and os.environ.get("EMBEDDING_MODEL"):
        return OpenAICompatEmbedder(cache_dir=os.environ.get("EMBEDDING_CACHE_DIR", ".cache/embeddings"))
    return FastembedEmbedder()  # offline fallback


@register("scored_recall", "recall")
class ScoredRecall:
    """Ranks the route's candidates by recency + importance + relevance; keeps rules plus the top TOP_K."""

    def __init__(self, embedder: Embedder | None = None) -> None:
        self._embedder = embedder
        self._vecs: dict[tuple[str, str], np.ndarray] = {}

    @property
    def embedder(self) -> Embedder | None:
        return self._embedder

    @embedder.setter
    def embedder(self, value: Embedder | None) -> None:
        self._embedder = value

    def recall(self, task: Task, store: Store, now: datetime, route: Route) -> str:
        r = route(store, task)
        rest = [*r.facts, *r.log]
        if rest:
            if self._embedder is None:
                self._embedder = _default_embedder()
            query = " ".join([*(str(v) for v in task.lead.values()), *task.tags])
            missing = [e for e in rest if (e.id, e.text) not in self._vecs]
            vecs = self._embedder.embed([*(e.text for e in missing), query])  # one call: new entries + query
            for e, v in zip(missing, vecs, strict=False):
                self._vecs[(e.id, e.text)] = np.asarray(v, dtype=float)
            q = np.asarray(vecs[len(missing)], dtype=float)
            rest = sorted(rest, key=lambda e: -score(e, q, self._vecs[(e.id, e.text)], now))[:TOP_K]
        entries = [*r.rules, *rest]
        store.touch([e.id for e in entries], now)
        return render(entries)
