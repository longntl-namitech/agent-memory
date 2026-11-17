from datetime import datetime

from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Event, WriteStage
from agent_memory.core.registry import register


@register("write_raw", "write")
class WriteRaw(WriteStage):
    """A1 stand-in when a config has no [write] stage: the event text becomes one log line, no LLM call."""

    def write(self, event: Event, store: Store, now: datetime, llm=None) -> list[Entry]:
        e = Entry(id=f"log-{len(store.all_log())}", kind="log", key=None, tags=event.tags, text=event.text,
                  importance=5, created_at=now, last_used_at=now, expires_at=None, status="active")
        store.add(e)
        return [e]
