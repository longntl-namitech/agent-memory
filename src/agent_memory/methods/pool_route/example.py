"""Route a small store with pool_route (no network)."""

import tempfile
from datetime import datetime
from pathlib import Path

from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Task
from agent_memory.methods.pool_route.stage import PoolRoute

NOW = datetime(2026, 1, 5, 9)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d))
        store.add(Entry("r1", "rule", None, [], "r1", 5, NOW, NOW, None, "active"))
        store.add(Entry("l1", "log", None, [], "l1", 5, NOW, NOW, None, "active"))
        print(PoolRoute()(store, Task(1, 1, 1, {}, ["acme"], wants_log=False)))
