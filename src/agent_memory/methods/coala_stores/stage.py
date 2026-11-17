from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Routed, Task
from agent_memory.core.registry import register

GLOBAL_TAG = "global"


@register("coala_stores", "sort")
class CoalaStores:
    """Route (callable `route(store, task) -> Routed`): RULES always, FACTS by tag, LOG only on request."""

    def __call__(self, store: Store, task: Task) -> Routed:
        facts: list[Entry] = []
        seen: set[str] = set()
        for tag in [*task.tags, GLOBAL_TAG]:
            for f in store.facts(tag):
                if f.id not in seen:
                    seen.add(f.id)
                    facts.append(f)
        return Routed(rules=store.rules(), facts=facts, log=store.log() if task.wants_log else [])
