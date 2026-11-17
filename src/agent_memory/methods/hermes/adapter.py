"""Hermes Agent as a whole-agent baseline: one `hermes -z` call per task in a dedicated data root per config.

Isolation: `profile_root` IS the Hermes data root (HERMES_HOME, never ~/.hermes), with a `config.yaml` the adapter
writes. No named profile and no `-p`: Hermes serves named profiles through a gateway that never sees our environment,
so the key would have to sit in the profile `.env`. The data root is reused across runs (its first use bootstraps a
~690 MB runtime); the run state (memory, sessions, logs) is wiped at start and again at close.
No `--ignore-user-config` (it would drop that config) and no `--ignore-rules` (it would skip memory).
The API key stays in the environment variable named by `key_env`; it is never read, written or logged here.
"""

import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from agent_memory.core.layout import Entry
from agent_memory.core.llm import TokenBudget
from agent_memory.core.memory import Agent, AgentResult, Task, task_message
from agent_memory.core.review import matches

DELIM = "\n§\n"  # Hermes memory entry delimiter (memory_tool_store.py)
MEMORY_CAP = 2_200  # memory.memory_char_limit default
FAILED = "hermes_failed"
_KEY_ENV = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
REPO = Path(__file__).resolve().parents[4]  # a relative profile_root is taken from the repo root, not the cwd
# Data-root entries that hold memory, conversation or session content (checked in the v0.23.2 sources, see
# docs/hermes-flags.md); wiped at start and close. The runtime (installs/, cache/, hermes-agent/ ...) is kept.
RUN_STATE = ("memories", "sessions", "state.db*", "checkpoints", "logs", "pending_messages", "response_store.db*",
             "workspace", "usage.json", "spawn-ledger.json*")  # the ledger keeps each call's argv, prompt included
_EPOCH = datetime(1970, 1, 1)  # MEMORY.md keeps no timestamps; the adapter never reads the clock


class HermesError(RuntimeError):
    """Hermes could not run a task at all (interrupted, timed out, crashed, no usage file)."""


def _entries(text: str) -> list[str]:
    return [e.strip() for e in text.split(DELIM) if e.strip()]


class MemoryMdStore:
    """The Store surface run_simulation and the Reviewer use (add, rules, all_rules, archive), over MEMORY.md.

    Every MEMORY.md entry counts as an active rule. Ids are content-based so they stay stable while
    `remove_blocklisted` archives one entry after another; archived entries are kept in memory only.
    """

    def __init__(self, agent: "HermesAgent"):
        self.agent = agent
        self._archived: list[Entry] = []

    @staticmethod
    def _id(text: str) -> str:
        return "m" + uuid.uuid5(uuid.NAMESPACE_OID, text).hex[:12]

    def _entry(self, text: str) -> Entry:
        return Entry(id=self._id(text), kind="rule", key=None, tags=["global"], text=text, importance=5,
                     created_at=_EPOCH, last_used_at=_EPOCH, expires_at=None, status="active")

    def add(self, entry: Entry) -> None:
        self.agent.plant_rule(entry.text)

    def rules(self) -> list[Entry]:
        return [self._entry(t) for t in self.agent.memory_entries()]

    def all_rules(self) -> list[Entry]:
        return self.rules() + list(self._archived)

    def archive(self, id: str, now: datetime | None = None) -> None:
        kept = []
        for text in self.agent.memory_entries():
            if self._id(text) == id:
                e = self._entry(text)
                e.status, e.archived_at = "archived", now
                self._archived.append(e)
            else:
                kept.append(text)
        self.agent.write_memory(kept)


class HermesAgent(Agent):
    """Runs each task as one fresh Hermes session; memory persists across tasks in the run's data root.

    A failed attempt (exit 2, or exit 1 / no text) returns `output=""` with `failed_check="hermes_failed"` and
    bumps `failed_attempts`: the runner then scores the empty output against the active rules as violations.
    Exit 130, any other exit code, a timeout or a missing usage file raise `HermesError`.
    Use as a context manager or call `close()`: it stops the gateway and wipes the run state.
    """

    def __init__(self, profile_root: Path, model: str, memory_enabled: bool, binary: str = "hermes", *,
                 base_url: str | None = None, key_env: str | None = None, max_turns: int = 20,
                 timeout: float = 600, budget: TokenBudget | None = None, env: dict | None = None,
                 install_home: Path = Path(".hermes-home")):
        if key_env is not None and not _KEY_ENV.fullmatch(key_env):
            raise ValueError(f"key_env must be an environment variable name, got {key_env!r}")
        self.profile_root = (REPO / profile_root).resolve()  # an absolute profile_root is kept as is
        # the bootstrapped install's home, only for `--version`: it exits 1 in a data root -z has not bootstrapped
        self.install_home = (REPO / install_home).resolve()
        self.model, self.memory_enabled, self.binary = model, memory_enabled, binary
        self.base_url, self.key_env, self.max_turns, self.timeout = base_url, key_env, max_turns, timeout
        self.budget = budget or TokenBudget(None)  # Hermes calls the model itself, so its usage is spent here
        self.env = {**os.environ, **(env or {}), "HERMES_HOME": str(self.profile_root)}
        self.workdir = self.profile_root / "workspace"  # cwd of each call: no AGENTS.md, wiped
        self.memory_path = self.profile_root / "memories" / "MEMORY.md"
        self.llm = None  # no LLMClient: the simulation's crash pricing must not look for one
        self.failed_attempts = 0
        self.planted_over_cap = False  # a plant that pushed MEMORY.md past its cap (kept, not refused)
        self.memory_sizes: list[int] = []  # MEMORY.md size at each Friday reflect, i.e. per week
        self.store = MemoryMdStore(self)
        self._pending: list[str] = []
        self._started = False

    @property
    def tokens_used(self) -> int:
        return self.budget.used

    def _call(self, args: list[str], cwd: Path, timeout: float | None = None,
              env: dict | None = None) -> subprocess.CompletedProcess:
        timeout = timeout or self.timeout
        try:
            return subprocess.run([self.binary, *args], env=env or self.env, cwd=cwd, capture_output=True, text=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise HermesError(f"hermes {args[0]} timed out after {timeout}s") from exc
        except FileNotFoundError as exc:
            raise HermesError(f"hermes binary {self.binary!r} not found (PATH={self.env.get('PATH', '')}); "
                              "set `binary` in the [hermes] config table") from exc

    # lifecycle

    def config_yaml(self) -> str:
        flag = "true" if self.memory_enabled else "false"
        lines = ["model:", f"  default: {json.dumps(self.model)}", "  provider: custom"]
        if self.base_url:
            lines.append(f"  base_url: {json.dumps(self.base_url)}")
        if self.key_env:
            lines.append(f"  key_env: {json.dumps(self.key_env)}")  # the NAME of the variable, never the key
        lines += ["agent:", f"  max_turns: {int(self.max_turns)}",
                  "memory:", f"  memory_enabled: {flag}", f"  user_profile_enabled: {flag}"]
        return "\n".join(lines) + "\n"

    def _wipe(self) -> None:
        for pattern in RUN_STATE:
            for p in self.profile_root.glob(pattern):
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)

    def start(self) -> None:
        """Reset the data root for a new run (wipe the run state, keep the runtime) and write its config; idempotent."""
        if self._started:
            return
        self._started = True  # before the reset, so close() also cleans a half-made one
        self.profile_root.mkdir(parents=True, exist_ok=True)
        self._wipe()  # also clears what a killed run left behind
        self.workdir.mkdir()
        (self.profile_root / "config.yaml").write_text(self.config_yaml(), encoding="utf-8")

    def close(self) -> None:
        """Stop the gateway a call may have auto-started, then wipe the run state: no memory outlives the run."""
        if not self._started:
            return
        try:
            self._call(["gateway", "stop"], self.profile_root, timeout=min(self.timeout, 60))
        except HermesError:
            pass  # timed out or no binary; a non-zero exit (nothing running) is ignored as well
        finally:
            self._wipe()
            self._started = False

    def __enter__(self) -> "HermesAgent":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def version(self) -> str:
        """The Hermes version, read under the install home; never raises (it only goes into the result header)."""
        cwd = self.install_home if self.install_home.is_dir() else Path.cwd()
        try:
            p = self._call(["--version"], cwd, timeout=min(self.timeout, 60),
                           env={**self.env, "HERMES_HOME": str(self.install_home)})
        except HermesError as exc:
            return f"unknown ({exc})"
        if p.returncode != 0:
            return f"unknown (hermes --version exited {p.returncode})"
        m = re.search(r"\d+\.\d+\.\d+\S*", p.stdout)
        return m.group(0) if m else p.stdout.strip()

    # Agent protocol

    def _prompt(self, task: Task) -> str:
        parts = [task_message(task)]  # the same task text the lab MemoryAgent sends
        if self._pending:
            parts.append("Corrections from me on earlier emails:\n" + "\n".join(f"- {t}" for t in self._pending))
        return "\n\n".join(parts)

    def _tokens(self, usage: Path) -> int:
        if not usage.exists():
            raise HermesError("hermes wrote no usage file, so its token spend is unknown")
        u = json.loads(usage.read_text(encoding="utf-8"))
        total = u.get("total_including_auxiliary")
        if isinstance(total, dict):
            total = total.get("total_tokens")
        if total is None:
            total = u.get("total_tokens")
        if total is None:  # a failed call writes every token field as null: it spent 0
            total = (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
        return int(total)

    def run_task(self, task: Task, now: datetime) -> AgentResult:
        self.start()
        usage = self.profile_root / "usage.json"
        usage.unlink(missing_ok=True)
        # no terminal, skills or file: skills and file writes would outlive the wipe, and file can read the repo
        # (corrections, blocklist, earlier results); an email needs none of them
        toolsets = "memory,todo" if self.memory_enabled else "todo"
        p = self._call(["-z", self._prompt(task), "--usage-file", str(usage),
                        "--provider", "custom", "-m", self.model, "-t", toolsets], self.workdir)
        self._pending = []
        if p.returncode not in (0, 1, 2):  # 130 interrupted, or a crash
            if usage.exists():
                self.budget.used += self._tokens(usage)  # record the spend; the raise below ends the task
            raise HermesError(f"hermes -z exited {p.returncode}: {p.stderr.strip()[-500:]}")
        tokens = self._tokens(usage)
        self.budget.spend(tokens)  # raises BudgetExceeded once the run is over its cap
        text = p.stdout.strip()
        if p.returncode != 0 or not text:  # 2 failed or partial, 1 completed with no text
            self.failed_attempts += 1
            return AgentResult("", "", 0, tokens, FAILED)
        return AgentResult(text, text, 0, tokens, None)

    def receive_correction(self, text: str, now: datetime) -> int:
        self._pending.append(text)  # sent as user text in the next task prompt
        return 0

    def end_task(self, task: Task, result: AgentResult, now: datetime) -> int:
        return 0  # Hermes decides what to save with its memory tool during the task

    def reflect(self, now: datetime) -> int:
        self.memory_sizes.append(self.memory_size())  # the runner reflects once per week, on Friday
        return 0

    # MEMORY.md plumbing for the simulation

    def _memory_text(self) -> str:
        # before start() the file may be a killed run's leftover, which start() wipes: it is not this run's memory
        return self.memory_path.read_text(encoding="utf-8") if self._started and self.memory_path.exists() else ""

    def memory_entries(self) -> list[str]:
        return _entries(self._memory_text())

    def write_memory(self, entries: list[str]) -> None:
        self.start()
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_path.write_text(DELIM.join(entries), encoding="utf-8")

    def memory_size(self) -> int:
        return len(self._memory_text())

    def plant_rule(self, text: str) -> None:
        # Never refused: a raise would abort the whole run. Hermes' own entries stay; T24 checks Hermes over the cap.
        entries = self.memory_entries() + [text.strip()]
        if len(DELIM.join(entries)) > MEMORY_CAP:
            self.planted_over_cap = True
        self.write_memory(entries)

    def review(self, blocklist) -> list[str]:
        """Remove every entry holding a blocklist marker (case and whitespace ignored); return their indexes."""
        markers = list(blocklist)
        entries = self.memory_entries()
        removed = [str(i) for i, e in enumerate(entries) if any(matches(e, m) for m in markers)]
        if removed:
            self.write_memory([e for i, e in enumerate(entries) if str(i) not in removed])
        return removed
