"""`agent-memory` command line. Subcommands: `review diff`, `run`."""

import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

from agent_memory.core.clock import SimClock
from agent_memory.core.config import build, load_config
from agent_memory.core.eval.checks import check
from agent_memory.core.eval.estimate import SUBSET_THRESHOLD, EstimateOnly, estimate, gate
from agent_memory.core.eval.lme_run import LMEAborted, check_lme_config, run_longmemeval
from agent_memory.core.eval.longmemeval import (ABILITIES, ability, download, first_questions,
                                                full_context_subset, load_selected)
from agent_memory.core.eval.report import write_result
from agent_memory.core.eval.simulation import DATA, SimulationAborted, active_rules, run_simulation
from agent_memory.core.layout import Store
from agent_memory.core.llm import BudgetExceeded, LLMClient, TokenBudget
from agent_memory.core.memory import Check, Task
from agent_memory.core.registry import ConfigError
from agent_memory.core.review import Reviewer, rules_diff

CONFIGS = Path(__file__).resolve().parents[2] / "configs"
SIM_START = datetime(2026, 1, 5)  # a Monday
SIM_SEED = 7  # the seed tasks.jsonl was generated with
PER_CONFIG_CAP = 100_000  # spec: each simulation config stays under 100k tokens
CACHE_NOTE = "shared across configs, so per-config tokens depend on run order"
LME_CACHE = Path(".cache")
LME_PER_ABILITY = 10
LME_SEED = 7
SUBSET_LIMIT = 1_000_000  # global rule: above 5M, first run a subset under 1M, then ask before the full set
JUDGE_NOTE = "{model} LLM judge (LongMemEval-style prompts), not comparable with the official GPT-4o judge"


def make_llm(budget: TokenBudget) -> LLMClient:
    """The one place a real LLM client is built; tests replace it."""
    return LLMClient(os.environ.get("OPENAI_BASE_URL"), os.environ.get("OPENAI_MODEL", "gpt-5.4-nano"),
                     budget, ".cache/llm")


def make_embedder():
    from agent_memory.methods.scored_recall.stage import _default_embedder

    return _default_embedder()


def sim_check(corrections: list[dict]) -> Check:
    """The retry check: the same rule checks and active-rule set the simulation scores the task with."""
    def first_failure(task: Task, output: str) -> str | None:
        failed = check(task, output, active_rules(task.id, corrections))
        return failed[0] if failed else None

    return first_failure


def _counters(agent) -> dict:
    """Parse-failure counters of the stages that keep one; each stage is one instance per run."""
    from agent_memory.methods.reflect.stage import Reflect
    from agent_memory.methods.reflexion.stage import Reflexion
    from agent_memory.methods.write_filter.stage import WriteFilter

    mem = agent.memory
    out = {}
    for s in [getattr(mem, "writer", None), *getattr(mem, "reflectors", []), *agent.retries]:
        if isinstance(s, WriteFilter):
            out["write_filter_fallbacks"] = s.fallbacks
        elif isinstance(s, Reflect):
            out["reflect_failures"] = s.failures
        elif isinstance(s, Reflexion):
            out["reflexion_fallbacks"] = s.fallbacks
    return out


def _results_path(results_dir: Path, name: str) -> Path:
    return results_dir / f"simulation_{name}.md"


def _run_simulation(name: str, llm: LLMClient, store_dir: Path, results_dir: Path) -> SimulationAborted | None:
    """Run one config and write its result; returns the abort, or None when it finished."""
    cfg = load_config(CONFIGS / f"{name}.toml")
    corrections = json.loads((DATA / "corrections.json").read_text(encoding="utf-8"))
    blocklist = json.loads((DATA / "blocklist.json").read_text(encoding="utf-8"))
    tasks = [Task(**json.loads(ln)) for ln in (DATA / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    embedder = make_embedder() if cfg.memory == "naive_rag" else None
    store = Store(store_dir)
    agent = build(cfg, llm=llm, store=store, check=sim_check(corrections),
                  **({"embedder": embedder} if embedder else {}))
    before = llm.budget.used
    extra, aborted = {"llm_cache": CACHE_NOTE}, None
    try:
        metrics = run_simulation(agent, tasks, SimClock(SIM_START), Reviewer([blocklist["marker"]]),
                                 store=store, corrections=corrections, blocklist=blocklist)
    except SimulationAborted as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        metrics, aborted = exc.metrics, exc
        extra |= {"partial": True, "completed_tasks": exc.completed_tasks, "crashed_tokens": exc.crashed_tokens}
    path = _results_path(results_dir, name)
    write_result(path, eval_name="simulation", config=name, model=llm.model,
                 embedding_model=embedder.name if embedder else "none", subset=f"all {len(tasks)} tasks",
                 seed=SIM_SEED, tokens=llm.budget.used - before,
                 metrics={f"week {w}": m for w, m in metrics.items()},
                 extra={**extra, **_counters(agent)}, run_date=date.today().isoformat())
    print(f"{name}: wrote {path}")
    return aborted


def _lme_table(result: dict) -> str:
    rows = ["| ability | correct | total | accuracy |", "| --- | --- | --- | --- |"]
    for a, v in [*result["by_ability"].items(), ("all", result)]:
        rows.append(f"| {a} | {v['correct']} | {v['total']} | {v['correct'] / v['total']:.0%} |"
                    if v["total"] else f"| {a} | 0 | 0 | - |")
    return "\n".join(rows)


def _lme_results_path(results_dir: Path, name: str) -> Path:
    return results_dir / f"longmemeval_{name}.md"


def _run_lme(args, names: list[str], est) -> int:
    """LongMemEval: one shared budget of --max-tokens; a failed config writes a PARTIAL result and stops the run."""
    if est.needs_subset and not args.confirm_full:
        print(f"refused: estimate above {SUBSET_THRESHOLD:,}. Run a subset under {SUBSET_LIMIT:,} first "
              f"(--questions 8), then ask before the full set and pass --confirm-full", file=sys.stderr)
        return 2
    if args.max_tokens is None:
        print("refused: --no-estimate-only needs --max-tokens (the run's total token cap)", file=sys.stderr)
        return 2
    cfgs = {n: load_config(CONFIGS / f"{n}.toml") for n in names}
    try:
        for c in cfgs.values():
            check_lme_config(c)
    except ConfigError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    out = args.out or Path(tempfile.mkdtemp(prefix="agent-memory-"))
    for n in names:
        if (out / n).exists():
            print(f"refused: {out / n} exists, a run needs a fresh store", file=sys.stderr)
            return 2
        if _lme_results_path(args.results_dir, n).exists() and not args.overwrite:
            print(f"refused: {_lme_results_path(args.results_dir, n)} exists (pass --overwrite to replace it)",
                  file=sys.stderr)
            return 2
    try:
        selected = load_selected(LME_CACHE, LME_PER_ABILITY, LME_SEED,
                                 download_fn=download if args.download else None)
    except FileNotFoundError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    rows = first_questions(selected, args.questions) if args.questions else selected

    llm = make_llm(TokenBudget(args.max_tokens))
    for n, cfg in cfgs.items():
        qs = full_context_subset(rows, args.full_context_questions) if cfg.memory == "full_context" else rows
        embedder = make_embedder() if cfg.memory == "naive_rag" or cfg.recall == "scored_recall" else None
        extra, aborted = {"llm_cache": CACHE_NOTE, "judge": JUDGE_NOTE.format(model=llm.model)}, None
        try:
            result = run_longmemeval(cfg, qs, llm, embedder=embedder, store_dir=out / n)
        except LMEAborted as exc:
            print(f"{n}: {exc}", file=sys.stderr)
            result, aborted = exc.result, exc
            extra |= {"partial": True, "completed_questions": exc.completed}
        path = _lme_results_path(args.results_dir, n)
        per = ", ".join(f"{sum(ability(r) == a for r in qs)} {a}" for a in ABILITIES)
        write_result(path, eval_name="longmemeval", config=n, model=llm.model,
                     embedding_model=embedder.name if embedder else "none",
                     subset=f"{len(qs)} questions ({per}) from the {len(selected)} selected", seed=LME_SEED,
                     tokens=result["tokens"], metrics=_lme_table(result), extra=extra,
                     run_date=date.today().isoformat())
        print(f"{n}: wrote {path}")
        if aborted is not None:
            return 1
    return 0


def _run(args, parser) -> int:
    names = [n.strip() for n in args.configs.split(",") if n.strip()]
    available = sorted(p.stem for p in CONFIGS.glob("*.toml"))
    if args.eval == "longmemeval":
        available = [n for n in available if n.startswith("lme_")]
    unknown = [n for n in names if n not in available]
    if unknown or not names:
        parser.error(f"unknown config(s): {', '.join(unknown) or '(none given)'}; available: {', '.join(available)}")

    est = estimate(args.eval, names, args.questions, args.full_context_questions)
    for n, t in est.by_config.items():
        print(f"{n}: {t}")
    print(f"total: {est.total} (prompt {est.prompt}, completion {est.completion})")
    print(f"above {SUBSET_THRESHOLD:,}: {'yes' if est.needs_subset else 'no'}")
    if args.eval == "simulation":
        print("note: the simulation per-task numbers are a placeholder (2,000 prompt + 500 completion per task)")
    try:
        gate(est, args.max_tokens, args.estimate_only)
    except EstimateOnly:
        print("estimate only, nothing was run (pass --no-estimate-only to run)")
        return 0
    except BudgetExceeded as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if args.eval == "longmemeval":
        return _run_lme(args, names, est)
    if est.needs_subset:
        print(f"refused: estimate above {SUBSET_THRESHOLD:,}, run a subset first", file=sys.stderr)
        return 2
    # Every refusal below happens before an LLM client is built or a file is written.
    if args.max_tokens is None:
        print("refused: --no-estimate-only needs --max-tokens (the run's total token cap)", file=sys.stderr)
        return 2
    out = args.out or Path(tempfile.mkdtemp(prefix="agent-memory-"))
    for n in names:
        if (out / n).exists():
            print(f"refused: {out / n} exists, a run needs a fresh store", file=sys.stderr)
            return 2
        if _results_path(args.results_dir, n).exists() and not args.overwrite:
            print(f"refused: {_results_path(args.results_dir, n)} exists (pass --overwrite to replace it)",
                  file=sys.stderr)
            return 2

    remaining, code = args.max_tokens, 0
    for i, n in enumerate(names):
        budget = TokenBudget(min(PER_CONFIG_CAP, remaining))
        aborted = _run_simulation(n, make_llm(budget), out / n, args.results_dir)
        remaining -= budget.used
        if aborted is None:
            continue
        code = 1
        if not isinstance(aborted.__cause__, BudgetExceeded):
            return 1  # a crash that is not a budget cap stops the run
        if remaining <= 0 and i + 1 < len(names):
            print(f"run budget spent, not run: {', '.join(names[i + 1:])}", file=sys.stderr)
            return 1
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-memory")
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("review").add_subparsers(dest="action", required=True)
    diff = review.add_parser("diff", help="print the RULES diff between two points in time")
    diff.add_argument("--store", type=Path, required=True)
    diff.add_argument("--from", dest="start", type=datetime.fromisoformat, required=True)
    diff.add_argument("--to", dest="end", type=datetime.fromisoformat, required=True)
    run = sub.add_parser("run", help="estimate (default) or run configs on an eval")
    run.add_argument("--eval", choices=["simulation", "longmemeval"], required=True)
    run.add_argument("--configs", required=True, help="comma-separated config names from configs/")
    run.add_argument("--estimate-only", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--max-tokens", type=int, help=(
        f"required with --no-estimate-only: the run's total token cap. Each config also gets its own cap of "
        f"min({PER_CONFIG_CAP:,}, what is left of the total). A config that hits its cap writes a PARTIAL result "
        f"and the run goes on with the next config; the run stops once the total is spent or a config "
        f"crashes for any other reason. Any partial result makes the exit code 1. On longmemeval the cap is one "
        f"budget shared by all configs, and the first config that hits it writes a PARTIAL result and ends the run."))
    run.add_argument("--questions", type=int, help=(
        "longmemeval: run only the first N selected questions, stratified evenly over the abilities "
        "(e.g. 8 for the subset run under 1,000,000 tokens)"))
    run.add_argument("--full-context-questions", type=int, default=10,
                     help="longmemeval: questions for lme_baseline_full_context (default 10)")
    run.add_argument("--download", action="store_true",
                     help="longmemeval: download the dataset into .cache/ if it is missing (the only network fetch)")
    run.add_argument("--confirm-full", action="store_true", help=(
        "longmemeval: allow a run whose estimate is above 5,000,000. Global rule: run a subset under "
        "1,000,000 first (--questions), then ask the user before the full set"))
    run.add_argument("--overwrite", action="store_true", help="replace existing results files")
    run.add_argument("--out", type=Path, help="where the per-config stores go (default: a temp dir)")
    run.add_argument("--results-dir", type=Path, default=Path("results"))
    args = parser.parse_args(argv)
    if args.command == "run":
        import agent_memory.methods  # noqa: F401  registers the stages before load_config/build

        return _run(args, run)
    if not args.store.is_dir():
        parser.error(f"no store at {args.store}")  # Store() would create an empty one
    print("\n".join(rules_diff(Store(args.store), args.start, args.end)))
    return 0
