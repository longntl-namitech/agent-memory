from agent_memory.core.layout import Store
from agent_memory.core.memory import Routed, Task
from agent_memory.core.registry import register


@register("pool_route", "sort")
class PoolRoute:
    """Route (callable) for configs without `[sort]`: every active entry is one pool, all in `facts`."""

    def __call__(self, store: Store, task: Task) -> Routed:
        return Routed(rules=[], facts=[*store.rules(), *store.facts(), *store.log()], log=[])
