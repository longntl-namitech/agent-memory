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
        # shortcut: vectors live in memory, parallel to store.log(); a store preloaded with log lines is not re-embedded
        self._vecs: list[np.ndarray] = []

    def write(self, event: Event, now: datetime) -> None:
        self._vecs.append(self.embedder.embed([event.text])[0])
        self.store.add(Entry(id=f"log-{len(self._vecs) - 1}", kind="log", key=None, tags=event.tags,
                             text=event.text, importance=5, created_at=now, last_used_at=now,
                             expires_at=None, status="active"))

    def recall(self, task: Task, now: datetime) -> str:
        if not self._vecs:
            return ""
        query = " ".join(str(task.lead.get(k, "")) for k in ("name", "company", "product"))
        hits = cosine_index(np.array(self._vecs))(self.embedder.embed([query])[0], TOP_K)
        log = self.store.log()
        return "\n".join(log[i].text for i, _ in hits)

    def reflect(self, now: datetime) -> None:
        pass

    def forget(self, now: datetime) -> None:
        pass
