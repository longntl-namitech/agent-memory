"""Route a small store with coala_stores (no network)."""

import tempfile
from datetime import datetime
from pathlib import Path

from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Task
from agent_memory.methods.coala_stores.stage import CoalaStores

NOW = datetime(2026, 1, 5, 9)


def entry(id, kind, tags):
    return Entry(id, kind, id if kind == "fact" else None, tags, id, 5, NOW, NOW, None, "active")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d))
        for e in (entry("r1", "rule", []), entry("f-acme", "fact", ["acme"]), entry("f-beta", "fact", ["beta"]),
                  entry("l1", "log", ["acme"])):
            store.add(e)
        task = Task(1, 1, 1, {}, ["acme"], wants_log=False)
        print(CoalaStores()(store, task))
