"""Render a small store with rules_only (no network)."""

import tempfile
from datetime import datetime
from pathlib import Path

from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Task
from agent_memory.methods.pool_route.stage import PoolRoute
from agent_memory.methods.rules_only.stage import RulesOnly

NOW = datetime(2026, 1, 5, 9)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d))
        store.add(Entry("r1", "rule", None, [], "Keep emails under 120 words.", 5, NOW, NOW, None, "active"))
        store.add(Entry("f1", "fact", "k", ["acme"], "ignored", 5, NOW, NOW, None, "active"))
        print(RulesOnly().recall(Task(1, 1, 1, {}, ["acme"], wants_log=False), store, NOW, PoolRoute()))
