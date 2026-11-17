"""Run write_filter with a canned LLM reply (no network)."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

from agent_memory.core.layout import Store
from agent_memory.core.llm import Completion
from agent_memory.core.memory import Event
from agent_memory.methods.write_filter.stage import WriteFilter


class CannedLLM:
    def chat(self, messages, *, purpose):
        reply = {"kind": "fact", "key": "Booking Link", "tags": ["acme"], "importance": 7,
                 "text": "Acme books through cal.example/acme"}
        return Completion(json.dumps(reply), 0, 0)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d))
        WriteFilter().write(Event("result", "long email transcript ...", ["acme"], "task"),
                            store, datetime(2026, 1, 5, 9), CannedLLM())
        print(store.render_markdown())
