from datetime import datetime

from agent_memory.core.layout import Entry, Store, slug
from agent_memory.core.registry import register


@register("forget", "overwrite")
class Overwrite:
    """Keeps one active fact per key: the earliest line's id and created_at, the newest line's content."""

    def forget(self, store: Store, now: datetime) -> None:
        groups: dict[str, list[Entry]] = {}
        for e in store.facts():  # active only, store order
            if e.key and slug(e.key):
                groups.setdefault(slug(e.key), []).append(e)
        for es in groups.values():
            if len(es) < 2:
                continue
            first = min(es, key=lambda e: e.created_at)  # min/max pick the first on ties
            last = max(reversed(es), key=lambda e: e.created_at)  # ties: later in store order wins
            store.replace_fact(first.id, last.text, last.tags, last.importance, last.expires_at, now)
            for e in es:
                if e is not first:
                    store.archive(e.id, now)
