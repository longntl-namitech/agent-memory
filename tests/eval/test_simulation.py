import json
from datetime import datetime
from pathlib import Path

import pytest

from agent_memory.core.clock import SimClock
from agent_memory.core.eval.checks import NEW_LINK, SIGN_OFF, check
from agent_memory.core.eval.simulation import SimulationAborted, WeekMetrics, active_rules, run_simulation
from agent_memory.core.layout import MAX_RULES, Entry, RulesFull, Store
from agent_memory.core.llm import BudgetExceeded, Completion, TokenBudget
from agent_memory.core.memory import AgentResult, MemoryAgent, StagedMemory, Task
from agent_memory.core.review import Reviewer

DATA = Path(__file__).resolve().parents[2] / "data" / "simulation"
CORRECTIONS = json.loads((DATA / "corrections.json").read_text())
BLOCKLIST = json.loads((DATA / "blocklist.json").read_text())
START = datetime(2026, 1, 5)  # a Monday


def load_tasks():
    return [Task(**json.loads(ln)) for ln in (DATA / "tasks.jsonl").read_text().splitlines() if ln.strip()]


def good_email():
    return f"Hi, 1,200 USD excl. VAT. Book {NEW_LINK}\n{SIGN_OFF}"


def perfect(task):
    return "SKIP" if task.lead.get("deal_status") == "closed" and task.id >= 14 else good_email()


class StubAgent:
    """Answers with answer(task); records every call with the simulated time."""

    def __init__(self, answer, first=None, tokens=10, raise_at=None):
        self.answer, self.first, self.tokens, self.raise_at = answer, first, tokens, raise_at
        self.calls = []

    def run_task(self, task, now):
        if task.id == self.raise_at:
            raise BudgetExceeded("over")
        self.calls.append(("task", task.id, now))
        out = self.answer(task)
        first = self.first(task) if self.first else out
        return AgentResult(out, first, int(first != out), self.tokens, None)

    def receive_correction(self, text, now):
        self.calls.append(("correction", text, now))
        return 0

    def end_task(self, task, result, now):
        self.calls.append(("end", task.id, now))
        return 0

    def reflect(self, now):
        self.calls.append(("reflect", now))
        return 0


class RecordingReviewer(Reviewer):
    def __init__(self, markers):
        super().__init__(markers)
        self.calls = []

    def review(self, store, now):
        self.calls.append(now)
        return super().review(store, now)


def run(agent, tmp_path, reviewer=None, tasks=None):
    return run_simulation(agent, tasks or load_tasks(), SimClock(START), reviewer, store=Store(tmp_path / "s"))


def test_never_violates_zero_corrections(tmp_path):
    m = run(StubAgent(perfect), tmp_path, Reviewer([BLOCKLIST["marker"]]))
    assert sorted(m) == [1, 2, 3, 4]
    for w in m.values():
        assert w == WeekMetrics(0, 0, 0, 0, 100)


def test_always_violates_counts_each_active_task(tmp_path):
    tasks = load_tasks()
    m = run(StubAgent(lambda t: ""), tmp_path, tasks=tasks)
    # Week 1: vat active from task 5 (5 tasks), sign_off from task 8 (2 tasks); every lead has a price.
    assert m[1].corrections == 7
    for week in (1, 2, 3, 4):
        expected = sum(len(check(t, "", active_rules(t.id, CORRECTIONS))) for t in tasks if t.week == week)
        assert m[week].corrections == m[week].first_attempt_failures == expected
    assert m[3].stale_fact_errors == sum(1 for t in tasks if t.week == 3 and t.lead["deal_status"] != "closed")
    assert m[1].stale_fact_errors == m[2].stale_fact_errors == 0


def test_first_attempt_failures_counted_separately(tmp_path):
    m = run(StubAgent(perfect, first=lambda t: ""), tmp_path, Reviewer([BLOCKLIST["marker"]]))
    assert all(w.corrections == 0 for w in m.values())
    assert m[1].first_attempt_failures == 7 and all(w.first_attempt_failures > 0 for w in m.values())


def test_friday_reflect_monday_review(tmp_path):
    agent, reviewer = StubAgent(perfect), RecordingReviewer([BLOCKLIST["marker"]])
    run(agent, tmp_path, reviewer)
    reflects = [c[1] for c in agent.calls if c[0] == "reflect"]
    assert [d.date() for d in reflects] == [datetime(2026, 1, d).date() for d in (9, 16, 23, 30)]
    assert all(d.weekday() == 4 for d in reflects)
    assert [d.date() for d in reviewer.calls] == [datetime(2026, 1, d).date() for d in (5, 12, 19, 26)]
    # The review runs before Monday's first task, reflect after Friday's last one.
    tasks = {c[1]: c[2] for c in agent.calls if c[0] == "task"}
    assert reviewer.calls[1] < tasks[10] and reflects[0] > tasks[9]
    assert (tasks[0], tasks[1]) == (datetime(2026, 1, 5, 9), datetime(2026, 1, 5, 11)) and tasks[9].weekday() == 4
    # The daily loop ends each task with end_task (write, forget), in task order.
    order = [(c[0], c[1]) for c in agent.calls if c[0] in ("task", "end")]
    assert order[:4] == [("task", 0), ("end", 0), ("task", 1), ("end", 1)]


def obeys_store(store):
    """Leaves the price out while the planted rule sits in RULES, as an agent following it would."""

    def answer(task):
        if task.lead.get("deal_status") == "closed" and task.id >= 14:
            return "SKIP"
        planted = any("never mention prices" in r.text.lower() for r in store.rules())
        return f"Hi. Book {NEW_LINK}\n{SIGN_OFF}" if planted else good_email()

    return answer


def test_planted_rule_removed_monday(tmp_path):
    tasks = load_tasks()
    priced_open = lambda week: sum(1 for t in tasks if t.week == week and not (t.lead["deal_status"] == "closed" and t.id >= 14))
    store = Store(tmp_path / "s")
    m = run_simulation(StubAgent(obeys_store(store)), tasks, SimClock(START), Reviewer([BLOCKLIST["marker"]]), store=store)
    assert m[1].extra_from_wrong_rule == 0 and m[2].extra_from_wrong_rule == priced_open(2) > 0
    assert m[2].corrections == m[2].extra_from_wrong_rule
    assert m[3].extra_from_wrong_rule == m[3].corrections == 0 and m[4].corrections == 0
    assert not any("never mention prices" in r.text.lower() for r in store.rules())

    # Without a reviewer the rule stays and keeps costing corrections.
    store2 = Store(tmp_path / "s2")
    m2 = run_simulation(StubAgent(obeys_store(store2)), tasks, SimClock(START), None, store=store2)
    assert [m2[w].extra_from_wrong_rule for w in (2, 3, 4)] == [priced_open(w) for w in (2, 3, 4)]


class FakeLLM:
    def __init__(self):
        self.budget = TokenBudget(None)

    def chat(self, messages, *, purpose):
        self.budget.spend(5)
        return Completion(good_email(), 2, 3)


def test_correction_written_as_event(tmp_path):
    events, log = [], []

    class Writer:
        def write(self, event, store, now, llm):
            llm.chat([], purpose="write")
            events.append((event, now))
            log.append(("write", event.kind))

    class Recall:
        def recall(self, task, store, now, route):
            log.append(("recall", task.id))
            return ""

    class Forget:
        def forget(self, store, now):
            log.append(("forget", now))

    store = Store(tmp_path / "s")
    llm = FakeLLM()
    agent = MemoryAgent(StagedMemory(store, llm, Writer(), None, Recall(), [], [Forget()]), llm)
    m = run_simulation(agent, load_tasks()[:6], SimClock(START), None, store=store)
    corrections = [(e, now) for e, now in events if e.kind == "correction"]
    vat = next(c for c in CORRECTIONS if c["id"] == "vat")
    (e, now), = corrections  # task 5 output passes, so only the activation is written
    assert (e.text, e.tags, e.source) == (vat["rule"], ["global"], "user")
    assert now.date() == datetime(2026, 1, 7).date()  # task 5 is Wednesday's second task
    i = log.index(("write", "correction"))
    assert log[i + 1] == ("recall", 5)
    assert [k for k, _ in log[:3]] == ["recall", "write", "forget"]  # recall, generate, write, forget
    # Tokens include writes outside run_task: 6 tasks x (task + result write) + 1 correction write.
    assert m[1].tokens == 6 * 10 + 5 == llm.budget.used


def test_violated_correction_written_again(tmp_path):
    agent = StubAgent(lambda t: "")
    run(agent, tmp_path, tasks=load_tasks()[:7])
    texts = [c[1] for c in agent.calls if c[0] == "correction"]
    vat = next(c["rule"] for c in CORRECTIONS if c["id"] == "vat")
    assert texts == [vat] * 3  # activation before task 5, then after tasks 5 and 6


def test_crash_keeps_partial_metrics(tmp_path):
    with pytest.raises(SimulationAborted) as info:
        run(StubAgent(lambda t: "", raise_at=12), tmp_path)
    exc = info.value
    assert exc.partial is True and exc.completed_tasks == 12
    assert isinstance(exc.__cause__, BudgetExceeded)
    assert sorted(exc.metrics) == [1, 2, 3, 4]
    assert exc.metrics[1].corrections == 7 and exc.metrics[1].tokens == 100
    assert exc.metrics[2].tokens == 20 and exc.metrics[3] == WeekMetrics(0, 0, 0, 0, 0)


def test_rules_full_aborts_with_partial_metrics(tmp_path):
    store = Store(tmp_path / "s")
    for i in range(MAX_RULES):
        store.add(Entry(id=f"r{i}", kind="rule", key=None, tags=[], text=f"rule {i}", importance=1,
                        created_at=START, last_used_at=START, expires_at=None, status="active"))
    with pytest.raises(SimulationAborted) as info:
        run_simulation(StubAgent(perfect), load_tasks(), SimClock(START), None, store=store)
    exc = info.value
    assert isinstance(exc.__cause__, RulesFull)  # the planted rule at task 10 is the 21st
    assert exc.completed_tasks == 10 and exc.metrics[1] == WeekMetrics(0, 0, 0, 0, 100)
    assert exc.metrics[2] == WeekMetrics(0, 0, 0, 0, 0)


class SpendingAgent(StubAgent):
    """Exposes `llm.budget` like MemoryAgent; spends tokens on the crashing task before raising."""

    def __init__(self, crash_at):
        super().__init__(perfect)
        self.llm = FakeLLM()
        self.crash_at = crash_at

    def run_task(self, task, now):
        self.llm.budget.spend(7)
        if task.id == self.crash_at:
            raise BudgetExceeded("over")
        return super().run_task(task, now)


def test_crashed_task_tokens_reported(tmp_path):
    with pytest.raises(SimulationAborted) as info:
        run(SpendingAgent(crash_at=3), tmp_path)
    exc = info.value
    assert exc.crashed_tokens == 7 and exc.completed_tasks == 3
    assert exc.metrics[1].tokens == 30  # finished tasks only; the crashed spend is reported separately
    with pytest.raises(SimulationAborted) as info:
        run(StubAgent(perfect, raise_at=3), tmp_path)
    assert info.value.crashed_tokens is None  # agent exposes no budget


def test_clock_must_start_on_monday(tmp_path):
    with pytest.raises(ValueError, match="Monday"):
        run_simulation(StubAgent(perfect), load_tasks(), SimClock(datetime(2026, 1, 6)), None, store=Store(tmp_path))
