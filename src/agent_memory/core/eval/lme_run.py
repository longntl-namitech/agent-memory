"""LongMemEval runner: per question, a fresh memory ingests the sessions at their timestamps, recalls, answers.

Cadence (spec): `reflect`, `reflexion`, `expire` and `archive` never run on this eval; only the `overwrite`
forget stage does, after each session. Hermes does not run here. Time comes only from the dataset dates.
"""

import re
import tempfile
from datetime import datetime
from pathlib import Path

from agent_memory.core.clock import SimClock
from agent_memory.core.config import Config, build
from agent_memory.core.eval.judge import judge
from agent_memory.core.eval.longmemeval import ABILITIES, ability
from agent_memory.core.layout import Store
from agent_memory.core.llm import LLMClient
from agent_memory.core.memory import Event, Task
from agent_memory.core.registry import ConfigError

_TAGS = ["global"]  # LongMemEval has no company slugs; `global` lets coala_stores route the facts
_ANSWER = ("You answer questions about past conversations with the user, using only the memory below. "
           "If the memory does not contain the answer, say that the information is not available.\n\n"
           "Memory:\n{memory}")


class LMEAborted(RuntimeError):
    """A question failed mid-run (e.g. BudgetExceeded); `result` covers the `completed` questions before it."""

    def __init__(self, result: dict, completed: int, cause: BaseException):
        super().__init__(f"longmemeval aborted after {completed} questions: {cause!r}")
        self.result = result
        self.completed = completed


def parse_date(text: str) -> datetime:
    """Dataset dates look like `2023/05/20 (Sat) 02:21`; the weekday is dropped, `/` or `-` and an optional time."""
    s = re.sub(r"\(\w+\)", " ", str(text))
    s = " ".join(s.split()).replace("/", "-")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(f"unparseable LongMemEval date: {text!r}") from None


def check_lme_config(cfg: Config) -> None:
    if cfg.agent:
        raise ConfigError(f"{cfg.name}: agent configs ({cfg.agent}) do not run on longmemeval; "
                          "hermes is simulation only")
    banned = [*cfg.reflect, *(n for n in cfg.forget if n != "overwrite")]
    if banned:
        raise ConfigError(f"{cfg.name}: {', '.join(banned)} never run on longmemeval "
                          "(only the overwrite forget stage does)")


def _render(session: list[dict]) -> str:
    return "\n".join(f"{t['role']}: {t['content']}" for t in session)


def _summary(name: str, per: dict, tokens: int) -> dict:
    return {"config": name, "total": sum(v["total"] for v in per.values()),
            "correct": sum(v["correct"] for v in per.values()), "tokens": tokens,
            "by_ability": {a: per[a] for a in ABILITIES if a in per}}


def run_longmemeval(config: Config, rows: list[dict], llm: LLMClient, *, embedder=None,
                    clock: SimClock | None = None, store_dir: Path | None = None) -> dict:
    """Run `config` on `rows`; each question gets a fresh store under `store_dir/<question_id>` (default a temp dir).

    Returns {config, total, correct, tokens, by_ability: {ability: {correct, total}}}; tokens is the budget delta.
    Raises LMEAborted (with the partial result) if a question fails.
    """
    check_lme_config(config)
    overwrite = "overwrite" in config.forget
    deps = {"embedder": embedder} if embedder is not None else {}
    before = llm.budget.used
    per: dict[str, dict] = {}
    for i, row in enumerate(rows):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                ok = _question(config, row, llm, deps, overwrite, clock,
                               Path(store_dir or tmp) / row["question_id"])
        except Exception as exc:  # BudgetExceeded included: keep the finished questions
            raise LMEAborted(_summary(config.name, per, llm.budget.used - before), i, exc) from exc
        a = per.setdefault(ability(row), {"correct": 0, "total": 0})
        a["total"] += 1
        a["correct"] += ok
    return _summary(config.name, per, llm.budget.used - before)


def _question(config, row, llm, deps, overwrite, clock, store_dir) -> bool:
    memory = build(config, llm=llm, store=Store(store_dir), **deps).memory
    recaller = getattr(memory, "recaller", None)
    if deps and hasattr(recaller, "_embedder") and recaller._embedder is None:
        recaller._embedder = deps["embedder"]  # scored_recall would build its own default otherwise
    sessions = sorted(zip(map(parse_date, row["haystack_dates"]), row["haystack_sessions"]), key=lambda s: s[0])
    for dt, session in sessions:
        now = _tick(clock, dt)
        memory.write(Event("session", _render(session), list(_TAGS), "longmemeval"), now)
        if overwrite:
            memory.forget(now)  # check_lme_config allows only overwrite in the forget list
    now = _tick(clock, parse_date(row["question_date"]))
    task = Task(id=0, week=0, day=0, lead={"question": row["question"]}, tags=list(_TAGS), wants_log=True)
    context = memory.recall(task, now)
    answer = llm.chat([{"role": "system", "content": _ANSWER.format(memory=context)},
                       {"role": "user", "content": f"Current date: {row['question_date']}\n"
                                                   f"Question: {row['question']}"}], purpose="answer").text
    qtype = "abstention" if ability(row) == "abstention" else row["question_type"]
    return judge(llm, row["question"], str(row["answer"]), answer, qtype)


def _tick(clock: SimClock | None, dt: datetime) -> datetime:
    if clock is None:
        return dt
    clock.set(dt)
    return clock.now()
