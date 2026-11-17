"""Run reflect with a canned LLM reply (no network)."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

from agent_memory.core.layout import Entry, Store
from agent_memory.core.llm import Completion
from agent_memory.methods.reflect.stage import Reflect


class CannedLLM:
    def chat(self, messages, *, purpose):
        reply = {"rules": [{"text": "Keep emails under 5 lines", "importance": 7, "sources": ["log-0"]}]}
        return Completion(json.dumps(reply), 0, 0)


if __name__ == "__main__":
    now = datetime(2026, 1, 9, 17)
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d))
        store.add(Entry("log-0", "log", None, ["acme"], "Acme liked the short email", 5, now, now, None, "active"))
        Reflect().reflect(store, now, CannedLLM())
        print(store.render_markdown())
