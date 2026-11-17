"""One chat turn: recall, a single LLM call, then (for memory columns) to-do changes and a memory write."""
from dataclasses import dataclass
from datetime import datetime

from agent_memory.core.layout import Store
from agent_memory.core.llm import LLMClient
from agent_memory.core.memory import Event, Memory, Task
from agent_memory.demo.todo import apply_actions, parse_reply

ASSISTANT_PROMPT = """You are a personal assistant. You only know what the MEMORY section below contains plus the user's current message.

Answer from the memory. If the memory does not contain the answer, say plainly that you do not know. Never invent personal details.

The user's to-do list is shown to you in the memory as facts whose key starts with `todo-`. Questions like "what is on my list" are answered from the memory.

Reply with ONLY a JSON object, nothing else:
{"reply": "<text for the user>", "todo": [{"action": "add|done|remove", "text": "<short item>"}]}
Leave `todo` empty unless the user asked to add, finish or remove something."""


@dataclass
class TurnResult:
    reply: str
    recalled: str
    tokens: int
    changed: list[str]


class PersonalAssistant:
    def __init__(self, memory: Memory, llm: LLMClient, store: Store, *, keeps_memory: bool):
        self.memory, self.llm, self.store, self.keeps_memory = memory, llm, store, keeps_memory

    def turn(self, text: str, now: datetime, turn_id: int) -> TurnResult:
        before = self.llm.budget.used
        task = Task(id=turn_id, week=0, day=0, lead={"message": text}, tags=["global"], wants_log=True)
        recalled = self.memory.recall(task, now)
        messages = [{"role": "system", "content": ASSISTANT_PROMPT + "\n\n## MEMORY\n" + (recalled or "(empty)")},
                    {"role": "user", "content": text}]
        reply, actions = parse_reply(self.llm.chat(messages, purpose="assistant").text)
        changed: list[str] = []
        if self.keeps_memory:
            changed = apply_actions(self.store, actions, now)
            self.memory.write(Event("chat", f"User: {text}\nAssistant: {reply}", ["global"], "user"), now)
        return TurnResult(reply, recalled, self.llm.budget.used - before, changed)
