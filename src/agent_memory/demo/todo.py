"""To-do list kept as facts (key prefix `todo-`, text `[open] ...` or `[done] ...`)."""
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from agent_memory.core.layout import Entry, Store, slug

TODO_PREFIX = "todo-"
_ACTIONS = {"add", "done", "remove"}
_MARKS = ("[open] ", "[done] ")


@dataclass
class Todo:
    key: str
    text: str
    done: bool


def parse_reply(raw: str) -> tuple[str, list[dict]]:
    m = re.search(r"\{.*\}", raw, re.S)  # greedy, like the lab stages
    try:
        d = json.loads(m.group(0)) if m else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("reply"), str):
        return raw.strip(), []
    items = d.get("todo")
    items = items if isinstance(items, list) else []
    return d["reply"], [a for a in items if isinstance(a, dict) and a.get("action") in _ACTIONS
                        and isinstance(a.get("text"), str) and a["text"].strip()]


def _ascii(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return slug("".join(c for c in nfd if not unicodedata.combining(c)))


def _key(text: str) -> str:
    # the hash keeps distinct texts apart (and non-ASCII-only text valid); same text, same key
    h = hashlib.sha1(unicodedata.normalize("NFC", text.strip().lower()).encode()).hexdigest()[:6]
    return "-".join(p for p in (TODO_PREFIX.rstrip("-"), _ascii(text)[:40].strip("-"), h) if p)


def _strip(text: str) -> str:
    return next((text[len(m):] for m in _MARKS if text.startswith(m)), text)


def _find(store: Store, text: str) -> Entry | None:
    items = [e for e in store.facts() if e.key.startswith(TODO_PREFIX)]
    for e in items:
        if e.key == _key(text):
            return e
    s, low = _ascii(text), text.lower()
    hits = [e for e in items if e.text.startswith("[open] ") and s and (s in e.key or low in e.text.lower())]
    return hits[0] if len(hits) == 1 else None  # never act on an ambiguous match


def apply_actions(store: Store, actions: list[dict], now: datetime) -> list[str]:
    keys = []
    for a in actions:
        text = a["text"].strip()
        if a["action"] == "add":
            key = _key(text)
            store.upsert_fact(Entry(id=f"fact-{key}-{len(store.all_facts())}", kind="fact", key=key, tags=["global"],
                                    text=f"[open] {text}", importance=5, created_at=now, last_used_at=now,
                                    expires_at=None, status="active"))
            keys.append(key)
            continue
        e = _find(store, text)
        if e is None:
            continue
        if a["action"] == "done":
            store.upsert_fact(Entry(id=e.id, kind="fact", key=e.key, tags=["global"], text=f"[done] {_strip(e.text)}",
                                    importance=5, created_at=e.created_at, last_used_at=now,
                                    expires_at=None, status="active"))
        else:
            store.archive(e.id, now)
        keys.append(e.key)
    return keys


def todos(store: Store) -> list[Todo]:
    return [Todo(e.key, _strip(e.text), e.text.startswith("[done] "))
            for e in store.facts() if e.key.startswith(TODO_PREFIX)]
