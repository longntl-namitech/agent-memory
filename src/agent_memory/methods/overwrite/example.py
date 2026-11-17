"""Two facts with the same key collapse into one line (no network)."""

import tempfile
from datetime import datetime
from pathlib import Path

from agent_memory.core.layout import Entry, Store
from agent_memory.methods.overwrite.stage import Overwrite

if __name__ == "__main__":
    t0, t1 = datetime(2026, 1, 1), datetime(2026, 1, 8)
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d))
        store.add(Entry("f-0", "fact", "Booking Link", [], "cal.com/old", 5, t0, t0, None, "active"))
        store.add(Entry("f-1", "fact", "booking-link", [], "cal.com/new", 5, t1, t1, None, "active"))
        Overwrite().forget(store, t1)
        print(store.render_markdown())
