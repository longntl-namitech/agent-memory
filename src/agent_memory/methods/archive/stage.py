from datetime import datetime, timedelta

from agent_memory.core.layout import Store
from agent_memory.core.registry import register

ARCHIVE_AFTER_DAYS = 30


@register("forget", "archive")
class Archive:
    """Archives every active rule not used (rendered by a recall stage) for 30 days or more."""

    def forget(self, store: Store, now: datetime) -> None:
        for e in store.rules():
            if now - e.last_used_at >= timedelta(days=ARCHIVE_AFTER_DAYS):
                store.archive(e.id, now)
