"""Render a small store with tag_recall (no network)."""

import tempfile
from datetime import datetime
from pathlib import Path

from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Task
from agent_memory.methods.coala_stores.stage import CoalaStores
from agent_memory.methods.tag_recall.stage import TagRecall

NOW = datetime(2026, 1, 5, 9)


def entry(id, kind, key, tags, text):
    return Entry(id, kind, key, tags, text, 5, NOW, NOW, None, "active")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d))
        store.add(entry("r1", "rule", None, [], "Keep emails under 120 words."))
        store.add(entry("f1", "fact", "booking-link", ["acme"], "cal.example.com/acme"))
        print(TagRecall().recall(Task(1, 1, 1, {}, ["acme"], wants_log=False), store, NOW, CoalaStores()))
