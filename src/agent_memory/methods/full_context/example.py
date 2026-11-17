"""Run full_context on a few toy events (no network, no LLM calls)."""

import tempfile
from datetime import datetime
from pathlib import Path


import agent_memory.methods  # noqa: F401
from agent_memory.core.layout import Store
from agent_memory.core.memory import Event, Task
from agent_memory.methods.full_context.stage import FullContext

if __name__ == "__main__":
    now = datetime(2026, 1, 5, 9)
    with tempfile.TemporaryDirectory() as d:
        mem = FullContext(Store(Path(d)))
        for text in ["Acme wants a quote", "Beta Corp booked a call", "Acme asked about VAT"]:
            mem.write(Event("result", text, [], "task"), now)
        task = Task(0, 1, 1, {"name": "Ann", "company": "Acme", "product": "alpha"}, ["acme"], False)
        print(mem.recall(task, now))
