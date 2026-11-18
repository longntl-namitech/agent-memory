import json
from datetime import datetime

import pytest

from agent_memory.core.layout import Store
from agent_memory.core.llm import BudgetExceeded, LLMClient, TokenBudget
from agent_memory.demo.todo import todos

NOW = datetime(2026, 1, 5, 9)


class FakeMemory:
    def __init__(self, recalled="", llm=None):
        self.recalled, self.llm, self.writes, self.tasks = recalled, llm, [], []

    def recall(self, task, now):
        self.tasks.append(task)
        return self.recalled

    def write(self, event, now):
        self.writes.append(event)
        if self.llm:
            self.llm.chat([{"role": "user", "content": event.text}], purpose="assistant_write")


def make(tmp_path, text, memory=None, cap=None, keeps=True):
    from agent_memory.demo.assistant import PersonalAssistant
    seen = []

    def transport(model, messages):
        seen.append(messages)
        return text, 10, 5

    llm = LLMClient("http://x", "m", TokenBudget(cap), tmp_path / "cache", transport=transport)
    memory = memory or FakeMemory()
    return PersonalAssistant(memory, llm, Store(tmp_path / "s"), keeps_memory=keeps), memory, llm, seen


def reply(r, todo=()):
    return json.dumps({"reply": r, "todo": list(todo)})


def test_recalled_text_reaches_the_prompt(tmp_path):
    a, mem, _, seen = make(tmp_path, reply("ok"), FakeMemory("Lan lives in Hanoi"))
    a.turn("Where do I live?", NOW, 3)
    system, user = seen[0]
    assert system["role"] == "system" and "Lan lives in Hanoi" in system["content"]
    assert user == {"role": "user", "content": "Where do I live?"}
    assert mem.tasks[0].id == 3 and mem.tasks[0].lead == {"message": "Where do I live?"}


def test_empty_recall_shows_empty_marker(tmp_path):
    a, _, _, seen = make(tmp_path, reply("ok"))
    a.turn("hi", NOW, 1)
    assert seen[0][0]["content"].endswith("## MEMORY\n(empty)")


def test_full_column_writes_and_applies_todo(tmp_path):
    a, mem, _, _ = make(tmp_path, reply("Added.", [{"action": "add", "text": "buy milk"}]))
    r = a.turn("add buy milk", NOW, 1)
    assert [t.text for t in todos(a.store)] == ["buy milk"]
    assert r.changed == [t.key for t in todos(a.store)] and r.reply == "Added."
    assert len(mem.writes) == 1
    ev = mem.writes[0]
    assert ev.kind == "chat" and "add buy milk" in ev.text and "Added." in ev.text


def test_no_memory_column_ignores_todo_and_writes_nothing(tmp_path):
    a, mem, _, _ = make(tmp_path, reply("Added.", [{"action": "add", "text": "buy milk"}]), keeps=False)
    r = a.turn("add buy milk", NOW, 1)
    assert todos(a.store) == [] and mem.writes == [] and r.changed == []


def test_tokens_are_budget_delta(tmp_path):
    mem = FakeMemory()
    a, mem, llm, _ = make(tmp_path, reply("ok"), mem)
    mem.llm = llm
    assert a.turn("hello", NOW, 1).tokens == 30  # chat 15 + write call 15
    assert a.turn("hello", NOW, 2).tokens == 0  # both served from the cache


def test_budget_exceeded_propagates(tmp_path):
    a, _, _, _ = make(tmp_path, reply("ok"), cap=1)
    with pytest.raises(BudgetExceeded):
        a.turn("hello", NOW, 1)


def test_invalid_json_reply_is_shown_as_is(tmp_path):
    a, _, _, _ = make(tmp_path, "just words")
    r = a.turn("hello", NOW, 1)
    assert r.reply == "just words" and r.changed == [] and todos(a.store) == []


def test_prompt_explains_empty_memory():
    from agent_memory.demo.assistant import ASSISTANT_PROMPT
    assert '"(empty)"' in ASSISTANT_PROMPT and "I don't know" in ASSISTANT_PROMPT
    assert len(ASSISTANT_PROMPT.split()) < 250
