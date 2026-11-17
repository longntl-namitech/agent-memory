"""Rank a small store with scored_recall, using a toy embedder (no network)."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Task
from agent_memory.methods.coala_stores.stage import CoalaStores
from agent_memory.methods.scored_recall.stage import ScoredRecall

NOW = datetime(2026, 1, 5, 9)


class Toy:
    name = "toy"

    def embed(self, texts):
        return np.array([[1.0, float("book" in t)] for t in texts])


def entry(id, kind, key, text, hours):
    return Entry(id, kind, key, ["acme"], text, 5, NOW, NOW - timedelta(hours=hours), None, "active")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d))
        store.add(entry("r1", "rule", None, "Keep emails under 120 words.", 0))
        store.add(entry("f1", "fact", "booking-link", "book at cal.example.com/acme", 300))
        store.add(entry("f2", "fact", "tone", "formal tone", 1))
        task = Task(1, 1, 1, {"name": "book a call"}, ["acme"], wants_log=False)
        print(ScoredRecall(Toy()).recall(task, store, NOW, CoalaStores()))
