from datetime import datetime
from pathlib import Path

from agent_memory.core.clock import SimClock

REPO = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ["src/agent_memory/core", "src/agent_memory/methods"]
FORBIDDEN = ["datetime.now(", "date.today(", "time.time("]


def test_advance_days():
    clock = SimClock(datetime(2026, 1, 5))
    clock.advance(days=7)
    assert clock.now() == datetime(2026, 1, 12)


def test_no_system_time():
    offenders = []
    for rel in SCANNED_DIRS:
        root = REPO / rel
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in FORBIDDEN:
                if needle in text:
                    offenders.append(f"{path.relative_to(REPO)}: {needle}")
    assert offenders == []
