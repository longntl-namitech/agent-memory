import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol

from agent_memory.core.layout import Entry, Store
from agent_memory.core.llm import LLMClient


@dataclass
class Event:
    kind: str
    text: str
    tags: list[str]
    source: str


@dataclass
class Task:
    id: int
    week: int
    day: int
    lead: dict
    tags: list[str]
    wants_log: bool


@dataclass
class RetryResult:
    output: str
    note: str


@dataclass
class AgentResult:
    output: str
    first_output: str
    retries: int
    tokens: int
    failed_check: str | None


class WriteStage(Protocol):
    """Persists its own entries to the store; the returned list is informational only."""

    def write(self, event: Event, store: Store, now: datetime, llm: LLMClient) -> list[Entry]: ...


class RecallStage(Protocol):
    def recall(self, task: Task, store: Store, now: datetime, route: Any) -> str: ...


class ForgetStage(Protocol):
    def forget(self, store: Store, now: datetime) -> None: ...


class ReflectStage(Protocol):
    def reflect(self, store: Store, now: datetime, llm: LLMClient) -> None: ...


class RetryStage(Protocol):
    """The returned note goes through memory.write, so the configured write stage may drop it."""

    def retry(self, task: Task, first_output: str, failed_check: str, context: str, llm: LLMClient) -> RetryResult: ...


class Memory(Protocol):
    def write(self, event: Event, now: datetime) -> None: ...
    def recall(self, task: Task, now: datetime) -> str: ...
    def reflect(self, now: datetime) -> None: ...
    def forget(self, now: datetime) -> None: ...


class Agent(Protocol):
    def run_task(self, task: Task, now: datetime) -> AgentResult: ...


@dataclass
class StagedMemory:
    """A Memory composed from one stage per slot. `route` is the sort stage, handed to recall."""

    store: Store
    llm: LLMClient
    writer: WriteStage
    route: Any
    recaller: RecallStage
    reflectors: list[ReflectStage]
    forgetters: list[ForgetStage]

    def write(self, event: Event, now: datetime) -> None:
        # The write stage persists its entries itself; nothing is added here, so no duplicates.
        self.writer.write(event, self.store, now, self.llm)

    def recall(self, task: Task, now: datetime) -> str:
        return self.recaller.recall(task, self.store, now, self.route)

    def reflect(self, now: datetime) -> None:
        for s in self.reflectors:
            s.reflect(self.store, now, self.llm)

    def forget(self, now: datetime) -> None:
        for s in self.forgetters:
            s.forget(self.store, now)


Check = Callable[[Task, str], str | None]  # returns the failed check's name, or None on pass


class MemoryAgent(Agent):
    """Recall, answer, and on a failed check run each retry stage once. The full loop lands in T9.

    Retry notes go through memory.write, so the configured write stage handles them (a filter may drop them).
    `tokens` is the budget.used delta over the whole task, so cache hits cost 0 and memory-internal calls count.
    """

    def __init__(self, memory: Memory, llm: LLMClient, retries: list[RetryStage] = (), check: Check | None = None):
        self.memory = memory
        self.llm = llm
        self.retries = list(retries)
        self.check = check

    def run_task(self, task: Task, now: datetime) -> AgentResult:
        before = self.llm.budget.used
        context = self.memory.recall(task, now)
        messages = [
            {"role": "system", "content": context},
            {"role": "user", "content": json.dumps({"lead": task.lead, "tags": task.tags}, ensure_ascii=False)},
        ]
        first = output = self.llm.chat(messages, purpose="task").text
        failed = self.check(task, output) if self.check else None
        n = 0
        for stage in self.retries:
            if failed is None:
                break
            r = stage.retry(task, output, failed, context, self.llm)
            self.memory.write(Event("reflection", r.note, task.tags, "retry"), now)
            output, n = r.output, n + 1
            failed = self.check(task, output)
        return AgentResult(output, first, n, self.llm.budget.used - before, failed)

