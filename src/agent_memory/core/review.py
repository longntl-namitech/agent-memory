"""The Review step: a scripted Monday reviewer and the RULES diff behind `agent-memory review diff`."""

from datetime import datetime
from typing import Iterable

from agent_memory.core.layout import Entry, Store


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def matches(text: str, marker: str) -> bool:
    """Case- and whitespace-insensitive substring match, so a rewritten rule is still caught."""
    return _norm(marker) in _norm(text)


def remove_blocklisted(store: Store, blocklist: Iterable[str], now: datetime | None = None) -> list[str]:
    """Archive every active rule holding a blocklist marker; return the ids the store really dropped."""
    markers = list(blocklist)
    before = [r.id for r in store.rules()]
    for r in store.rules():
        if any(matches(r.text, m) for m in markers):
            store.archive(r.id, now)
    after = {r.id for r in store.rules()}
    return [i for i in before if i not in after]


class Reviewer:
    """The scripted reviewer: runs each simulated Monday and deletes blocklisted rules."""

    def __init__(self, blocklist: Iterable[str]):
        self.blocklist = list(blocklist)

    def review(self, store: Store, now: datetime) -> list[str]:
        return remove_blocklisted(store, self.blocklist, now)


def rules_at(store: Store, t: datetime) -> list[Entry]:
    # shortcut: a rule archived without a timestamp counts as gone at every point, pass `now` to archive().
    return [r for r in store.all_rules() if r.created_at <= t
            and (r.status == "active" or (r.archived_at is not None and r.archived_at > t))]


def rules_diff(store: Store, start: datetime, end: datetime) -> list[str]:
    a, b = rules_at(store, start), rules_at(store, end)
    a_ids, b_ids = {r.id for r in a}, {r.id for r in b}
    return ([f"--- RULES at {start.isoformat()}", f"+++ RULES at {end.isoformat()}"]
            + [f"- {r.text}" for r in a if r.id not in b_ids]
            + [f"+ {r.text}" for r in b if r.id not in a_ids])
