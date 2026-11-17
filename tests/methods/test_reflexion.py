import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from agent_memory.core.llm import BudgetExceeded, Completion
from agent_memory.core.memory import MemoryAgent, Task
from agent_memory.methods.reflexion.stage import Reflexion

NOW = datetime(2026, 1, 5, 9)
TASK = Task(1, 1, 1, {"name": "Ann", "company": "Acme"}, ["acme"], False)


class StubLLM:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.budget = SimpleNamespace(used=0)

    def chat(self, messages, *, purpose):
        self.calls.append((purpose, messages))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return Completion(r, 1, 1)


class RecMemory:
    def __init__(self):
        self.events = []

    def write(self, event, now):
        self.events.append(event)

    def recall(self, task, now):
        return "CONTEXT"

    def reflect(self, now): ...

    def forget(self, now): ...


def j(note="check the VAT line", output="fixed"):
    return json.dumps({"note": note, "output": output})


def agent(llm, check, mem=None):
    mem = mem or RecMemory()
    return MemoryAgent(mem, llm, [Reflexion()], check), mem


def test_prompt_names_failed_check():
    llm = StubLLM(j())
    r = Reflexion().retry(TASK, "first draft", "vat", "CONTEXT", llm)
    purpose, msgs = llm.calls[0]
    text = json.dumps(msgs)
    assert purpose == "reflexion" and len(llm.calls) == 1
    assert "vat" in text and "first draft" in text and "CONTEXT" in text and "Acme" in text
    assert (r.output, r.note) == ("fixed", "check the VAT line")


def test_parses_fenced_json_with_prose():
    llm = StubLLM("Sure:\n```json\n" + j("n", "o") + "\n```\nDone")
    r = Reflexion().retry(TASK, "a", "vat", "", llm)
    assert (r.output, r.note) == ("o", "n")


def test_garbage_falls_back_without_second_call():
    s, llm = Reflexion(), StubLLM("just a plain email")
    r = s.retry(TASK, "a", "vat", "", llm)
    assert (r.output, r.note, s.fallbacks, len(llm.calls)) == ("just a plain email", "", 1, 1)


def test_budget_exceeded_propagates():
    with pytest.raises(BudgetExceeded):
        Reflexion().retry(TASK, "a", "vat", "", StubLLM(BudgetExceeded("x")))


def test_one_retry_only():
    llm = StubLLM("first", j(output="second"))
    a, _ = agent(llm, lambda t, o: "vat")  # fails every time
    res = a.run_task(TASK, NOW)
    assert (res.output, res.first_output, res.retries, res.failed_check) == ("second", "first", 1, "vat")
    assert [c[0] for c in llm.calls] == ["task", "reflexion"]


def test_no_retry_when_check_passes():
    llm = StubLLM("first")
    a, mem = agent(llm, lambda t, o: None)
    res = a.run_task(TASK, NOW)
    assert (res.retries, res.output, len(llm.calls), mem.events) == (0, "first", 1, [])


def test_note_written_to_memory():
    llm = StubLLM("first", j(note="remember VAT"))
    a, mem = agent(llm, lambda t, o: "vat" if o == "first" else None)
    res = a.run_task(TASK, NOW)
    assert res.failed_check is None
    assert [(e.kind, e.text, e.source) for e in mem.events] == [("reflection", "remember VAT", "retry")]


def test_empty_note_not_written():
    llm = StubLLM("first", "plain retry")
    a, mem = agent(llm, lambda t, o: "vat" if o == "first" else None)
    a.run_task(TASK, NOW)
    assert mem.events == []


def test_prompt_carries_rule_wording_and_skip_instruction():
    llm = StubLLM(j())
    Reflexion().retry(TASK, "a", "sign_off", "", llm)
    text = llm.calls[0][1][0]["content"]
    assert "sign_off: End every email with the exact sign-off" in text
    assert "Best regards, Sam from Brightpath" in text
    assert "exactly SKIP" in text
