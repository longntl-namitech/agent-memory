from datetime import datetime

from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Route, Task
from agent_memory.core.registry import register


def render(entries: list[Entry]) -> str:
    """RULES, FACTS, LOG in that order, each entry by its own kind; empty sections omitted; text only."""
    lines = {"rule": lambda e: e.text, "fact": lambda e: f"{e.key}: {e.text}", "log": lambda e: e.text}
    sections = []
    for kind, title in (("rule", "RULES"), ("fact", "FACTS"), ("log", "LOG")):
        body = [lines[kind](e) for e in entries if e.kind == kind]
        if body:
            sections.append("\n".join([f"## {title}", *body]))
    return "\n\n".join(sections)


@register("tag_recall", "recall")
class TagRecall:
    """Renders whatever the route selected; it does no selection of its own."""

    def recall(self, task: Task, store: Store, now: datetime, route: Route) -> str:
        r = route(store, task)
        entries = [*r.rules, *r.facts, *r.log]
        store.touch([e.id for e in entries], now)
        return render(entries)
