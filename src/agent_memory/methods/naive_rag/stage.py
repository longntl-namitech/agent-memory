from datetime import datetime

import numpy as np

from agent_memory.core.embed import Embedder, cosine_index
from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Event, Memory, Task
from agent_memory.core.registry import register

TOP_K = 5


@register("naive_rag", "memory")
class NaiveRag(Memory):
    """Baseline: embed every event, recall the TOP_K most cosine-similar to the task's lead text."""

    def __init__(self, store: Store, llm=None, *, embedder: Embedder, **_deps) -> None:
        self.store = store
        self.embedder = embedder
        # shortcut: vectors and texts live in memory; a store preloaded with log lines is not re-embedded
        self._vecs: list[np.ndarray] = []
        self._texts: list[str] = []
        self._ids: list[str] = []
        self._n = len(store.all_log())  # archived lines count too, so ids never repeat

    def write(self, event: Event, now: datetime) -> None:
        self._vecs.append(self.embedder.embed([event.text])[0])
        self._texts.append(event.text)
        self._ids.append(f"log-{self._n}")
        self.store.add(Entry(id=f"log-{self._n}", kind="log", key=None, tags=event.tags,
                             text=event.text, importance=5, created_at=now, last_used_at=now,
                             expires_at=None, status="active"))
        self._n += 1

    def recall(self, task: Task, now: datetime) -> str:
        if not self._vecs:
            return ""
        query = " ".join(str(task.lead.get(k, "")) for k in ("name", "company", "product"))
        # over-fetch (all hits), then keep the first TOP_K that are still active in the store
        hits = cosine_index(np.array(self._vecs))(self.embedder.embed([query])[0], len(self._vecs))
        active = {e.id for e in self.store.log()}
        return "\n".join([self._texts[i] for i, _ in hits if self._ids[i] in active][:TOP_K])

    def reflect(self, now: datetime) -> None:
        pass

    def forget(self, now: datetime) -> None:
        pass
