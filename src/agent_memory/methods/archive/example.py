"""A rule unused for 30 days is archived; one used 29 days ago stays (no network)."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from agent_memory.core.layout import Entry, Store
from agent_memory.methods.archive.stage import Archive

if __name__ == "__main__":
    now = datetime(2026, 3, 1)
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d))
        for id, days in (("r-29", 29), ("r-30", 30)):
            t = now - timedelta(days=days)
            store.add(Entry(id, "rule", None, [], f"rule used {days} days ago", 5, t, t, None, "active"))
        Archive().forget(store, now)
        print("active rules:", [e.id for e in store.rules()])
