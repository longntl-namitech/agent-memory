import json
import re
from datetime import datetime

from agent_memory.core.layout import MAX_RULES, Entry, Store
from agent_memory.core.llm import LLMClient
from agent_memory.core.registry import register

MAX_NEW_RULES = 3

_PROMPT = """You are the weekly reflection of an agent memory. Read the log lines and the current rules, then distil at most {n} NEW rules: instructions to follow on every future task that the log lines support.
Reply with JSON only: {{"rules": [{{"text": str, "importance": 1-10, "sources": [log ids the rule came from]}}]}}
- Do not repeat a current rule. Reply {{"rules": []}} if nothing new is worth a rule.
Current rules:
{rules}
Log lines:
{log}"""


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


@register("reflect", "reflect")
class Reflect:
    """One LLM call turns active log lines into at most 3 rules and archives the lines they came from."""

    def __init__(self) -> None:
        self.failures = 0  # replies that were not usable JSON

    def reflect(self, store: Store, now: datetime, llm: LLMClient) -> None:
        log = store.log()
        if not log:
            return
        prompt = _PROMPT.format(
            n=MAX_NEW_RULES,
            rules="\n".join(f"- {r.text}" for r in store.rules()) or "(none)",
            log="\n".join(f"- {e.id}: {e.text}" for e in log))
        reply = llm.chat([{"role": "user", "content": prompt}], purpose="reflect").text
        cands = self._parse(reply)
        if cands is None:
            self.failures += 1
            return
        log_ids = {e.id for e in log}
        added: set[str] = set()
        for text, importance, sources in cands[:MAX_NEW_RULES]:
            if any(_norm(r.text) == _norm(text) for r in store.rules()):
                # pure duplicate of an active rule: the lesson is already kept, so the sources can go
                self._archive_sources(store, sources & log_ids, now)
                continue
            # archive first so store.add never raises RulesFull; the pass's own new rules are never evicted
            keep = [r for r in store.rules() if r.id not in added]
            for r in sorted(keep, key=lambda r: (r.importance, r.last_used_at, r.id))[
                    :max(0, len(store.rules()) + 1 - MAX_RULES)]:
                store.archive(r.id, now)
            if len(store.rules()) >= MAX_RULES:
                continue
            rid = f"rule-{len(store.all_rules())}"
            store.add(Entry(id=rid, kind="rule", key=None, tags=["global"], text=text, importance=importance,
                            created_at=now, last_used_at=now, expires_at=None, status="active"))
            added.add(rid)
            self._archive_sources(store, sources & log_ids, now)

    @staticmethod
    def _archive_sources(store: Store, ids: set[str], now: datetime) -> None:
        for i in sorted(ids):
            store.archive(i, now)

    @staticmethod
    def _parse(reply: str) -> list[tuple[str, int, set[str]]] | None:
        """Return (text, importance, source ids) per usable rule, or None when the reply is not usable JSON.

        Same approach as write_filter's parser (greedy brace match tolerates fences), copied rather than imported.
        """
        m = re.search(r"\{.*\}", reply, re.S)
        try:
            items = json.loads(m.group(0))["rules"] if m else None
        except (TypeError, KeyError, ValueError):
            return None
        if not isinstance(items, list):
            return None
        out = []
        for d in items:
            if not isinstance(d, dict) or not str(d.get("text") or "").strip():
                continue
            try:
                imp = min(10, max(1, int(d.get("importance", 5))))
            except (TypeError, ValueError):
                imp = 5
            src = d.get("sources")
            out.append((str(d["text"]).strip(), imp,
                        {str(s) for s in src} if isinstance(src, list) else set()))
        return out
