"""Run reflexion with a canned LLM reply (no network)."""

import json

from agent_memory.core.llm import Completion
from agent_memory.core.memory import Task
from agent_memory.methods.reflexion.stage import Reflexion


class CannedLLM:
    def chat(self, messages, *, purpose):
        return Completion(json.dumps({"note": "Always mention VAT.", "output": "Hi Ann, prices exclude VAT."}), 0, 0)


if __name__ == "__main__":
    task = Task(1, 1, 1, {"name": "Ann", "company": "Acme"}, ["acme"], False)
    print(Reflexion().retry(task, "Hi Ann, our price is 100.", "vat", "(no memory)", CannedLLM()))
