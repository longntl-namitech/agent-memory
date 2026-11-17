"""4-week simulation runner: daily loop, scripted corrections, planted wrong rule, Monday review, Friday reflect."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from agent_memory.core.clock import SimClock
from agent_memory.core.eval.checks import check
from agent_memory.core.layout import Entry, Store
from agent_memory.core.memory import Agent, Task
from agent_memory.core.review import Reviewer, matches

DATA = Path(__file__).resolve().parents[4] / "data" / "simulation"
# The planted rule forbids prices, so following it breaks the VAT rule (quote prices excl. VAT).
PLANTED_COSTS = {"vat"}
STALE = "booking_link"


@dataclass
class WeekMetrics:
    corrections: int = 0
    first_attempt_failures: int = 0
    stale_fact_errors: int = 0
    extra_from_wrong_rule: int = 0
    tokens: int = 0


class SimulationAborted(RuntimeError):
    """Raised when the agent fails mid-run; carries the per-week metrics of every finished task.

    `crashed_tokens` is what the unfinished step spent (budget delta), or None if the agent exposes no budget.
    """

    partial = True

    def __init__(self, metrics: dict[int, WeekMetrics], completed_tasks: int, cause: BaseException,
                 crashed_tokens: int | None = None):
        super().__init__(f"simulation aborted after {completed_tasks} tasks: {cause!r}")
        self.metrics = metrics
        self.completed_tasks = completed_tasks
        self.crashed_tokens = crashed_tokens


def _load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def active_rules(task_id: int, corrections: list[dict]) -> set[str]:
    return {c["id"] for c in corrections if c["active_from_task"] <= task_id}


def run_simulation(agent: Agent, tasks: list[Task], clock: SimClock, reviewer: Reviewer | None, *,
                   store: Store | None = None, corrections: list[dict] | None = None,
                   blocklist: dict | None = None) -> dict[int, WeekMetrics]:
    """Run the tasks in order. `store` is the agent's store (default `agent.memory.store`); the planted
    rule goes there and the reviewer edits it. `reviewer=None` means no Monday review."""
    store = store if store is not None else agent.memory.store
    corrections = corrections if corrections is not None else _load("corrections.json")
    blocklist = blocklist if blocklist is not None else _load("blocklist.json")
    start = clock.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if start.weekday() != 0:
        raise ValueError(f"the simulation clock must start on a Monday, got {start.date()}")

    def at(task: Task, hour: int) -> datetime:
        return start + timedelta(days=(task.week - 1) * 7 + task.day - 1, hours=hour)

    metrics = {w: WeekMetrics() for w in sorted({t.week for t in tasks})}
    rule_text = {c["id"]: c["rule"] for c in corrections}
    told: set[str] = set()
    done = 0
    # Only to price a crashed step: the per-call token returns above it are lost when a call raises.
    budget = getattr(getattr(agent, "llm", None), "budget", None)
    used = lambda: budget.used if budget is not None else 0
    mark = used()
    try:
        for i, task in enumerate(tasks):
            m = WeekMetrics()  # this task's share, added to its week only once the task finishes
            mark = used()
            prev, nxt = tasks[i - 1] if i else None, tasks[i + 1] if i + 1 < len(tasks) else None
            new_day = prev is None or (prev.week, prev.day) != (task.week, task.day)
            slot = 0 if new_day else slot + 1
            if new_day and task.day == 1 and reviewer is not None:
                clock.set(at(task, 8))
                reviewer.review(store, clock.now())
            clock.set(at(task, 9 + 2 * slot))
            now = clock.now()
            # Planted after the Monday review, so it survives until the next Monday.
            if task.id == blocklist["plant_at_task"]:
                store.add(Entry(id="planted-wrong-rule", kind="rule", key=None, tags=["global"],
                                text=blocklist["planted_rule"], importance=5, created_at=now,
                                last_used_at=now, expires_at=None, status="active"))
            active = active_rules(task.id, corrections)
            for rid in sorted(active - told, key=list(rule_text).index):
                m.tokens += agent.receive_correction(rule_text[rid], now)
                told.add(rid)
            planted = any(matches(r.text, blocklist["marker"]) for r in store.rules())

            result = agent.run_task(task, now)
            m.tokens += result.tokens
            violated = check(task, result.output, active)
            m.corrections += len(violated)
            m.first_attempt_failures += len(check(task, result.first_output, active))
            m.stale_fact_errors += STALE in violated
            if planted:
                m.extra_from_wrong_rule += len(PLANTED_COSTS.intersection(violated))
            for rid in violated:  # the user corrects what they saw, as they would say it
                m.tokens += agent.receive_correction(rule_text[rid], now)
            m.tokens += agent.end_task(task, result, now)
            week = metrics[task.week]
            for f in vars(m):
                setattr(week, f, getattr(week, f) + getattr(m, f))
            done += 1

            if task.day == 5 and (nxt is None or (nxt.week, nxt.day) != (task.week, task.day)):
                clock.set(at(task, 17))
                mark = used()
                week.tokens += agent.reflect(clock.now())
    except Exception as exc:  # BudgetExceeded included: keep what was measured so far
        crashed = used() - mark if budget is not None else None
        raise SimulationAborted(metrics, done, exc, crashed) from exc
    return metrics
