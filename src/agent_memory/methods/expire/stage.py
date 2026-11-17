from datetime import datetime, timedelta

from agent_memory.core.layout import Store
from agent_memory.core.registry import register

EXPIRY_DAYS = 7


@register("expire", "forget")
class Expire:
    """Gives active log lines `expires_at = created_at + 7 days` and archives any active entry whose expiry has passed."""

    def forget(self, store: Store, now: datetime) -> None:
        for e in store.log():
            if e.expires_at is None:
                store.set_expiry(e.id, e.created_at + timedelta(days=EXPIRY_DAYS))
        for e in store.log() + store.facts():
            if e.expires_at is not None and now >= e.expires_at:
                store.archive(e.id, now)
