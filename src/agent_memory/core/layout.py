import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

MAX_RULES = 20
_KINDS = ("rule", "fact", "log")
_TIME_FIELDS = ("created_at", "last_used_at", "expires_at")


class RulesFull(Exception):
    pass


@dataclass
class Entry:
    id: str
    kind: Literal["rule", "fact", "log"]
    key: str | None
    tags: list[str]
    text: str
    importance: int
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime | None
    status: Literal["active", "archived"]


def slug(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")


def _dump(e: Entry) -> str:
    d = asdict(e)
    for f in _TIME_FIELDS:
        d[f] = d[f].isoformat() if d[f] else None
    return json.dumps(d)


def _load(line: str) -> Entry:
    d = json.loads(line)
    for f in _TIME_FIELDS:
        d[f] = datetime.fromisoformat(d[f]) if d[f] else None
    return Entry(**d)


class Store:
    """JSONL file per kind plus a rendered MEMORY.md. Rewrites files on every change."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, list[Entry]] = {}
        for k in _KINDS:
            p = self._path(k)
            lines = p.read_text().splitlines() if p.exists() else []
            self._entries[k] = [_load(ln) for ln in lines if ln.strip()]

    def _path(self, kind: str) -> Path:
        return self.root / f"{kind}s.jsonl" if kind != "log" else self.root / "log.jsonl"

    def _save(self) -> None:
        for k in _KINDS:
            text = "".join(_dump(e) + "\n" for e in self._entries[k])
            self._path(k).write_text(text)
        (self.root / "MEMORY.md").write_text(self.render_markdown())

    def _active(self, kind: str) -> list[Entry]:
        return [e for e in self._entries[kind] if e.status == "active"]

    def add(self, e: Entry) -> None:
        if e.kind == "rule" and e.status == "active" and len(self._active("rule")) >= MAX_RULES:
            raise RulesFull(f"already {MAX_RULES} active rules")
        if e.kind == "fact" and e.key:
            e.key = slug(e.key)
        self._entries[e.kind].append(e)
        self._save()

    def upsert_fact(self, e: Entry) -> None:
        e.key = slug(e.key or "")
        for old in self._active("fact"):
            if old.key == e.key:
                old.text, old.last_used_at = e.text, e.last_used_at
                self._save()
                return
        self.add(e)

    def rules(self) -> list[Entry]:
        return self._active("rule")

    def facts(self, tag: str | None = None) -> list[Entry]:
        return [e for e in self._active("fact") if tag is None or tag in e.tags]

    def log(self) -> list[Entry]:
        return list(self._entries["log"])

    def archive(self, id: str) -> None:
        for es in self._entries.values():
            for e in es:
                if e.id == id:
                    e.status = "archived"
        self._save()

    def render_markdown(self) -> str:
        def sec(title: str, es: list[Entry]) -> str:
            lines = [f"- {e.key + ': ' if e.key else ''}{e.text}" for e in es]
            return "\n".join([f"## {title}", *lines])

        return "\n\n".join([sec("RULES", self.rules()), sec("FACTS", self.facts()),
                            sec("LOG", self.log())]) + "\n"
