"""Demo-only registrations: a memory that remembers nothing and a write stage that keeps several entries per turn."""

import json
import re
from datetime import datetime

import agent_memory.methods  # noqa: F401  registers the lab stages the demo configs name
from agent_memory.core.layout import MAX_RULES, Entry, Store, slug
from agent_memory.core.llm import LLMClient
from agent_memory.core.memory import Event, Task, WriteStage
from agent_memory.core.registry import register
from agent_memory.demo.todo import TODO_PREFIX

_KINDS = ("rule", "fact", "log")
MAX_ENTRIES = 6
_TAGS = ["global"]  # the demo has one user, so every entry applies everywhere; the model never picks tags

_PROMPT = """You are the memory writer of a personal chat assistant. Read the chat turn and write down what is worth remembering about the USER.
Reply with JSON only: {{"entries": [{{"kind": "fact"|"rule"|"log", "key": str, "text": str, "importance": 1-10}}]}}
- At most {max_entries} entries. Use an empty list when nothing is worth remembering.
- text: a short distilled statement about the user in the third person ("The user lives in Hanoi."), never a transcript.
- fact: ONE stable detail about the user per entry (name, city, job, family, likes): write the name and the city as two facts, not one.
  The key names the attribute ("name", "city", "job"), never the value ("lives-in-hanoi" is wrong), so a new value overwrites the old one.
  Reuse one of these existing keys if it is the same attribute, do not invent a variant: {keys}
- rule: only a standing preference or instruction for how the assistant should always behave.
- log: anything else worth a line, including one-off situations ("this week I'm on a diet").
- Reminders and to-do items are handled elsewhere: do NOT record them.
Chat turn: {text}"""


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


@register("no_memory", "memory")
class NoMemory:
    """The no-memory column: every call is a no-op and recall is always empty."""

    def __init__(self, store: Store, llm: LLMClient, **deps) -> None:
        self.store, self.llm = store, llm

    def write(self, event: Event, now: datetime) -> None:
        pass

    def recall(self, task: Task, now: datetime) -> str:
        return ""

    def reflect(self, now: datetime) -> None:
        pass

    def forget(self, now: datetime) -> None:
        pass


@register("assistant_write", "write")
class AssistantWrite(WriteStage):
    """One LLM call per chat turn returns up to MAX_ENTRIES facts, rules and log lines about the user."""

    def __init__(self) -> None:
        self.fallbacks = 0  # turns written as a raw log line because the reply was unusable
        self.dropped_rules = 0  # rules skipped because MAX_RULES active rules already exist
        self.skipped_entries = 0  # malformed single entries (unknown kind, empty text, not an object)

    def write(self, event: Event, store: Store, now: datetime, llm: LLMClient) -> list[Entry]:
        keys = sorted({f.key for f in store.facts() if not f.key.startswith(TODO_PREFIX)})  # to-dos are not the model's
        prompt = _PROMPT.format(max_entries=MAX_ENTRIES, keys=", ".join(keys) or "(none)", text=event.text)
        items = self._parse(llm.chat([{"role": "user", "content": prompt}], purpose="assistant_write").text)
        if items is None:
            self.fallbacks += 1
            items = [{"kind": "log", "key": "", "text": event.text, "importance": 5}]
        out = []
        for d in items[:MAX_ENTRIES]:
            e = self._write_one(d, store, now)
            if e is not None:
                out.append(e)
        return out

    def _write_one(self, d: dict, store: Store, now: datetime) -> Entry | None:
        kind, key = d["kind"], slug(d["key"])
        if kind == "fact" and (not key or key.startswith(TODO_PREFIX)):
            kind = "log"  # a fact needs a key to be overwritten later; a to-do key is never overwritten by a fact
        mk = lambda id_, key=None: Entry(id=id_, kind=kind, key=key, tags=list(_TAGS), text=d["text"],
                                         importance=d["importance"], created_at=now, last_used_at=now,
                                         expires_at=None, status="active")
        if kind == "rule":
            if any(_norm(r.text) == _norm(d["text"]) for r in store.rules()):
                return None  # duplicate
            if len(store.rules()) >= MAX_RULES:
                self.dropped_rules += 1
                return None  # the cap is hit: skip rather than raise RulesFull
            e = mk(f"rule-{len(store.all_rules())}")
            store.add(e)
        elif kind == "fact":
            # all_facts counts archived ones too, so ids never repeat; no clock in the id: replays must match
            store.upsert_fact(mk(f"fact-{key}-{len(store.all_facts())}", key))
            e = next(f for f in store.facts() if f.key == key)  # on an overwrite this is the old entry
        else:
            e = mk(f"log-{len(store.all_log())}")
            store.add(e)
        return e

    def _parse(self, reply: str) -> list[dict] | None:
        """Clean entries, or None when the reply is unusable. Malformed single entries are skipped."""
        m = re.search(r"\{.*\}", reply, re.S)  # tolerate a code fence around the JSON
        try:
            raw = json.loads(m.group(0))["entries"] if m else None
        except (ValueError, KeyError, TypeError):
            return None
        if not isinstance(raw, list):
            return None
        items = []
        for d in raw:
            if not isinstance(d, dict):
                self.skipped_entries += 1
                continue
            kind, text = str(d.get("kind", "")).strip().lower(), str(d.get("text") or "").strip()
            if kind not in _KINDS or not text:
                self.skipped_entries += 1
                continue
            try:
                imp = min(10, max(1, int(d.get("importance", 5))))
            except (TypeError, ValueError):
                imp = 5
            items.append({"kind": kind, "key": str(d.get("key") or ""), "text": text, "importance": imp})
        return items
