"""A log line is archived 7 days after it was created (no network)."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from agent_memory.core.layout import Entry, Store
from agent_memory.methods.expire.stage import Expire

if __name__ == "__main__":
    t0 = datetime(2026, 1, 1)
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d))
        store.add(Entry("l-0", "log", None, [], "one-off: lead asked to call on Friday", 5, t0, t0, None, "active"))
        Expire().forget(store, t0 + timedelta(days=6))
        print("day 6:", [e.id for e in store.log()])
        Expire().forget(store, t0 + timedelta(days=7))
        print("day 7:", [e.id for e in store.log()])
