"""Run naive_rag on a few toy events (no network, no LLM calls)."""

import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np

import agent_memory.methods  # noqa: F401
from agent_memory.core.layout import Store
from agent_memory.core.memory import Event, Task
from agent_memory.methods.naive_rag.stage import NaiveRag


class Toy:
    name = "toy"

    def embed(self, texts):
        return np.array([[len(t), t.count("a") + 1, 1] for t in texts], dtype=float)

if __name__ == "__main__":
    now = datetime(2026, 1, 5, 9)
    with tempfile.TemporaryDirectory() as d:
        mem = NaiveRag(Store(Path(d)), embedder=Toy())
        for text in ["Acme wants a quote", "Beta Corp booked a call", "Acme asked about VAT"]:
            mem.write(Event("result", text, [], "task"), now)
        task = Task(0, 1, 1, {"name": "Ann", "company": "Acme", "product": "alpha"}, ["acme"], False)
        print(mem.recall(task, now))
