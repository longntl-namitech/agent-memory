from datetime import datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SimClock(Clock):
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, *, days: int = 0, hours: int = 0) -> None:
        self._now += timedelta(days=days, hours=hours)

    def set(self, dt: datetime) -> None:
        self._now = dt
