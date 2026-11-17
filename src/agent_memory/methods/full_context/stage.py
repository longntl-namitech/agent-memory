from datetime import datetime

from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Event, Memory, Task
from agent_memory.core.registry import register


@register("full_context", "memory")
class FullContext(Memory):
    """Baseline: every event is kept verbatim and the whole history is the prompt. Grows without bound."""

    def __init__(self, store: Store, llm=None, **_deps) -> None:
        self.store = store
        self._n = len(store._entries["log"])  # archived lines count too, so ids never repeat

    def write(self, event: Event, now: datetime) -> None:
        self.store.add(Entry(id=f"log-{self._n}", kind="log", key=None, tags=event.tags, text=event.text,
                             importance=5, created_at=now, last_used_at=now, expires_at=None, status="active"))
        self._n += 1

    def recall(self, task: Task, now: datetime) -> str:
        return "\n".join(e.text for e in self.store.log())

    def reflect(self, now: datetime) -> None:
        pass

    def forget(self, now: datetime) -> None:
        pass
