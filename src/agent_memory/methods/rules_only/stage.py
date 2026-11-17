from datetime import datetime

from agent_memory.core.layout import Store
from agent_memory.core.memory import Route, Task
from agent_memory.core.registry import register
from agent_memory.methods.tag_recall.stage import render


@register("rules_only", "recall")
class RulesOnly:
    """Recall for configs without `[recall]`: the active rules, ignoring the route."""

    def recall(self, task: Task, store: Store, now: datetime, route: Route) -> str:
        rules = store.rules()
        store.touch([e.id for e in rules], now)
        return render(rules)
