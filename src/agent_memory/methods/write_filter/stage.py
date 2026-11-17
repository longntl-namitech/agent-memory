import json
import re
from datetime import datetime

from agent_memory.core.layout import MAX_RULES, Entry, Store, slug
from agent_memory.core.llm import LLMClient
from agent_memory.core.memory import Event, WriteStage
from agent_memory.core.registry import register

FALLBACKS = 0  # events written as a raw log line because the reply was unusable; never reset by the stage
_KINDS = ("rule", "fact", "log")

_PROMPT = """You are the write filter of an agent memory. Turn the event into ONE short lesson to remember, never a transcript.
Reply with JSON only: {{"kind": "rule"|"fact"|"log", "key": str, "tags": [str], "importance": 1-10, "text": str}}
- rule: an instruction to follow on every future task. fact: a stable detail about a person or company; give it a short key.
  log: anything else worth a line.
- text: the distilled lesson in your own words.
- For a fact, reuse one of these existing keys if it is the same fact, do not invent a variant: {keys}
Event kind: {kind}
Event tags: {tags}
Event text: {text}"""


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


@register("write_filter", "write")
class WriteFilter(WriteStage):
    """One LLM call per event decides kind, key, tags, importance and the distilled lesson text."""

    def write(self, event: Event, store: Store, now: datetime, llm: LLMClient) -> list[Entry]:
        keys = sorted({f.key for t in event.tags for f in store.facts(t)} or {f.key for f in store.facts()})
        prompt = _PROMPT.format(keys=", ".join(keys) or "(none)", kind=event.kind,
                                tags=", ".join(event.tags) or "(none)", text=event.text)
        reply = llm.chat([{"role": "user", "content": prompt}], purpose="write_filter").text
        d = self._parse(reply)
        if d is None:
            global FALLBACKS
            FALLBACKS += 1
            d = {"kind": "log", "text": event.text, "tags": [], "importance": 5}
        kind, text = d["kind"], d["text"]
        tags = event.tags + [t for t in d["tags"] if t not in event.tags]
        mk = lambda k, key=None, id_=None: Entry(id=id_, kind=k, key=key, tags=tags, text=text,
                                                 importance=d["importance"], created_at=now, last_used_at=now,
                                                 expires_at=None, status="active")
        if kind == "rule":
            if len(store.rules()) >= MAX_RULES or any(_norm(r.text) == _norm(text) for r in store.rules()):
                return []  # duplicate, or the cap is hit: skip rather than raise RulesFull
            e = mk("rule", id_=f"rule-{len(store.all_rules())}")
            store.add(e)
        elif kind == "fact":
            e = mk("fact", slug(d["key"]), f"fact-{slug(d['key'])}-{len(store.facts())}-{now:%Y%m%d%H%M%S}")
            store.upsert_fact(e)
        else:
            e = mk("log", id_=f"log-{len(store.all_log())}")
            store.add(e)
        return [e]

    @staticmethod
    def _parse(reply: str) -> dict | None:
        """Return a clean dict, or None when the reply is unusable (caller falls back to a log line)."""
        m = re.search(r"\{.*\}", reply, re.S)  # tolerate a code fence around the JSON
        try:
            d = json.loads(m.group(0)) if m else None
            text = str(d["text"]).strip()
            kind = d["kind"]
            if kind not in _KINDS or not text or (kind == "fact" and not slug(str(d.get("key") or ""))):
                return None
            tags = d.get("tags") or []
            imp = d.get("importance", 5)
            return {"kind": kind, "key": str(d.get("key") or ""), "text": text,
                    "tags": [t for t in tags if isinstance(t, str)] if isinstance(tags, list) else [],
                    "importance": min(10, max(1, int(imp)))}
        except (TypeError, KeyError, ValueError):
            return None
