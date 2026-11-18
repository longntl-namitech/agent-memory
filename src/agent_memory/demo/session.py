"""One demo session: a shared clock and two columns (no memory, full memory) answering the same messages."""
import os
import shutil
import threading
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agent_memory.core.clock import SimClock
from agent_memory.core.config import build, load_config
from agent_memory.core.layout import Store
from agent_memory.core.llm import BudgetExceeded, TokenBudget
from agent_memory.demo.assistant import PersonalAssistant
from agent_memory.demo.clients import ReplayMiss, is_live_failure, make_embedder, make_llm, redact
from agent_memory.demo.paths import DemoPaths
from agent_memory.demo.script import PERSONA, PROMPTS, SECOND_ACT
from agent_memory.demo.todo import TODO_PREFIX, todos

COLUMNS = ("none", "full")
START = datetime(2026, 1, 5, 9)
_CONFIGS = {"none": "demo_no_memory", "full": "demo_full"}
_TITLES = {"none": "No memory", "full": "Full memory"}
_MISS = "Not in the rehearsed script, replay cannot answer"


@dataclass
class ColumnTurn:
    reply: str | None
    error: str | None
    tokens: int = 0
    recalled: str = ""


@dataclass
class _Column:
    assistant: PersonalAssistant
    store: Store
    budget: TokenBudget
    recalled: str = ""
    error: str | None = None
    new: set = field(default_factory=set)  # entry ids written by the last action
    replaced: dict = field(default_factory=dict)  # fact id -> old text


def _active(store: Store) -> dict:
    return {e.id: e for e in (*store.rules(), *store.facts(), *store.log())}


class Session:
    def __init__(self, paths: DemoPaths, *, mode: str, max_tokens: int, base_url: str, model: str,
                 config_dir: Path, transport=None, embed_transport=None) -> None:
        if mode not in ("live", "warmup", "replay"):
            raise ValueError(f"unknown mode: {mode!r}")
        self.paths, self.mode, self.max_tokens = paths, mode, max_tokens
        self.base_url, self.model, self.config_dir = base_url, model, Path(config_dir)
        self.transport, self.embed_transport = transport, embed_transport
        self._lock = threading.RLock()  # serialises actions
        self._snap_lock = threading.Lock()  # guards only the stored snapshot, never held across a slow call
        self._busy, self._snap = 0, {}
        self.reset()

    @contextmanager
    def _act(self):
        with self._snap_lock:
            self._busy += 1
        try:
            with self._lock:
                try:
                    yield
                finally:
                    snap = self._build_snapshot()
                    with self._snap_lock:
                        self._snap = snap
        finally:
            with self._snap_lock:
                self._busy -= 1

    # -- construction -------------------------------------------------------------------------
    def _secrets(self) -> list[str]:
        return [s for s in (os.environ.get("OPENAI_API_KEY"), os.environ.get("EMBEDDING_API_KEY")) if s]

    def _build(self, col: str, budget: TokenBudget) -> _Column:
        self.paths.ensure()
        store = Store(self.paths.store(col))
        llm = make_llm(self.mode, self.paths, budget, base_url=self.base_url, model=self.model,
                       transport=self.transport)
        memory = build(load_config(self.config_dir / f"{_CONFIGS[col]}.toml"), llm=llm, store=store).memory
        if col == "full":
            memory.recaller.embedder = make_embedder(
                self.mode, self.paths, base_url=os.environ.get("EMBEDDING_BASE_URL") or "unset",
                model=os.environ.get("EMBEDDING_MODEL") or "unset", api_key=os.environ.get("EMBEDDING_API_KEY"),
                transport=self.embed_transport)
        return _Column(PersonalAssistant(memory, llm, store, keeps_memory=col == "full"), store, budget)

    def _rebuild(self, budgets: dict | None = None) -> None:
        self.cols = {c: self._build(c, (budgets or {}).get(c) or TokenBudget(self.max_tokens)) for c in COLUMNS}

    # -- helpers ------------------------------------------------------------------------------
    def _error_text(self, exc: BaseException) -> str:
        if isinstance(exc, BudgetExceeded):
            return "Token cap reached"
        if isinstance(exc, ReplayMiss):
            return _MISS
        return redact(str(exc), self._secrets())

    def _track(self, col: _Column, fn):
        """Run fn, then record which entries it wrote (new) and which facts it rewrote (replaced)."""
        before = {i: e.text for i, e in _active(col.store).items()}  # Store mutates entries in place: copy the text
        try:
            return fn()
        finally:
            col.new, col.replaced = set(), {}
            for i, e in _active(col.store).items():
                if i not in before or before[i] != e.text:
                    col.new.add(i)
                    if e.kind == "fact" and i in before:
                        col.replaced[i] = before[i]

    def _guard(self, col: _Column, fn) -> None:
        try:
            fn()
            col.error = None
        except Exception as exc:  # per-column error, never raised
            col.error = self._error_text(exc)

    # -- actions ------------------------------------------------------------------------------
    def _column_turn(self, col: _Column, text: str, now: datetime, turn_id: int):
        try:
            r = self._track(col, lambda: col.assistant.turn(text, now, turn_id))
        except Exception as exc:
            col.recalled, col.error = "", self._error_text(exc)
            return ColumnTurn(None, col.error), exc
        col.recalled, col.error = r.recalled, None
        return ColumnTurn(r.reply, None, r.tokens, r.recalled), None

    def _run_turn(self, text: str):
        self._n += 1
        now = self.clock.now()
        with ThreadPoolExecutor(len(COLUMNS)) as ex:
            futs = {c: ex.submit(self._column_turn, self.cols[c], text, now, self._n) for c in COLUMNS}
            res = {c: f.result() for c, f in futs.items()}
        return {c: r[0] for c, r in res.items()}, [r[1] for r in res.values() if r[1] is not None]

    def turn(self, text: str) -> dict[str, ColumnTurn]:
        with self._act():
            self.history.append(text)
            out, excs = self._run_turn(text)
            if self.mode == "live" and any(is_live_failure(e) for e in excs):
                self._failover()
                out = self._replay_history()
            return out

    def _replay_history(self) -> dict[str, ColumnTurn]:
        out = {}
        for t in self.history:
            out, _ = self._run_turn(t)
        return out

    def _failover(self) -> None:
        self.mode = "replay"
        try:
            self._clear_state(keep_budgets=True)
        except BaseException:
            self.mode = "live"
            raise
        self.notice = f"Live call failed, switched to replay. {self._rebuilt_note()}"

    def _rebuilt_note(self) -> str:
        n = len(self.history)
        return (f"Memory rebuilt from your {n} message{'s' if n != 1 else ''}. "
                "The date, reflect and forgotten items were reset.")

    def _clear_state(self, keep_budgets: bool = False) -> None:
        self.clock, self._n = SimClock(START), 0
        for c in COLUMNS:
            shutil.rmtree(self.paths.store(c), ignore_errors=True)
        # the token cap guards real spend, so a mode switch or failover keeps what was already used
        self._rebuild({c: v.budget for c, v in self.cols.items()} if keep_budgets else None)

    def forget(self, column: str, entry_id: str) -> bool:
        with self._act():
            col = self.cols.get(column)
            if col is None:
                return False
            # a to-do is addressed by its key (the card has no id), anything else by id; active entries only
            hit = next((e for e in _active(col.store).values()
                        if e.id == entry_id or (e.key == entry_id and entry_id.startswith(TODO_PREFIX))), None)
            if hit is None:
                return False
            self._track(col, lambda: col.store.archive(hit.id, self.clock.now()))
            return True

    def advance(self) -> None:
        with self._act():
            self.clock.advance(days=1)
            for col in self.cols.values():
                self._guard(col, lambda: self._track(col, lambda: col.assistant.memory.forget(self.clock.now())))

    def reflect(self) -> None:
        with self._act():
            col, now = self.cols["full"], self.clock.now()
            self._guard(col, lambda: self._track(col, lambda: (col.assistant.memory.reflect(now),
                                                              col.assistant.memory.forget(now))))

    def set_mode(self, mode: str) -> None:
        if mode not in ("live", "replay"):
            raise ValueError(f"unknown mode: {mode!r}")
        with self._act():
            self.notice = None
            if mode == self.mode:
                return
            old, self.mode = self.mode, mode
            try:
                if mode == "replay":
                    self._clear_state(keep_budgets=True)
                else:
                    self._rebuild({c: v.budget for c, v in self.cols.items()})
            except BaseException:
                self.mode = old
                raise
            if mode == "replay":
                self._replay_history()
                if self.history:
                    self.notice = f"Switched to replay. {self._rebuilt_note()}"

    def reset(self) -> None:
        with self._act():
            self.history: list[str] = []
            self.notice: str | None = None
            self._clear_state()

    def wipe(self) -> None:
        with self._act():
            self.paths.wipe()
            self.reset()

    # -- view ---------------------------------------------------------------------------------
    def snapshot(self) -> dict:
        """The state after the last completed action; never waits for a running one."""
        with self._snap_lock:
            return {**self._snap, "busy": self._busy > 0}

    def _build_snapshot(self) -> dict:
        if True:
            def entries(col: _Column, es):
                return [{"id": e.id, "key": e.key, "text": e.text, "created_at": e.created_at.isoformat(),
                         "new": e.id in col.new, "replaced_from": col.replaced.get(e.id)} for e in es]

            columns = {}
            for c, col in self.cols.items():
                st = col.store
                columns[c] = {
                    "title": _TITLES[c],
                    "entries": {"rules": entries(col, st.rules()),
                                "facts": entries(col, [e for e in st.facts() if not e.key.startswith(TODO_PREFIX)]),
                                "log": entries(col, st.log())},
                    "todos": todos(st), "tokens": col.budget.used, "recalled": col.recalled, "error": col.error}
            return {"date": self.clock.now().strftime("%a %Y-%m-%d"), "mode": self.mode, "cap": self.max_tokens,
                    "notice": self.notice,
                    "prompts": {"persona": PERSONA, "script": list(PROMPTS), "second_act": SECOND_ACT},
                    "columns": columns}
