"""`agent-memory` command line. Subcommands: `review diff`, `run`."""

import argparse
import dataclasses
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from agent_memory.core.clock import SimClock
from agent_memory.core.config import build, load_config
from agent_memory.core.eval.checks import check
from agent_memory.core.eval.estimate import LME_NOTE, SUBSET_THRESHOLD, EstimateOnly, estimate, gate
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
HERMES_BOOTSTRAP_NOTE = ("note: the first Hermes call in a new data root bootstraps a ~690 MB runtime "
                         "(installs Python dependencies) and can take minutes")
CACHE_NOTE = "shared across configs, so per-config tokens depend on run order"
LME_CACHE = Path(".cache")
DEMO_DEFAULT_ROOT = Path(__file__).resolve().parents[2] / ".demo"
LME_PER_ABILITY = 10
LME_SEED = 7
SUBSET_LIMIT = 1_000_000  # global rule: above 5M, first run a subset under 1M, then ask before the full set
REFLEXION_NOTE = ("corrections are counted after an oracle-guided retry; "
                  "compare memory methods on first_attempt_failures")
BASELINE_NA = "n/a (baseline has no RULES)"
JUDGE_NOTE = "{model} LLM judge (LongMemEval prompts), not comparable with the official GPT-4o judge"


def make_llm(budget: TokenBudget) -> LLMClient:
    """The one place a real LLM client is built; tests replace it."""
    return LLMClient(os.environ.get("OPENAI_BASE_URL"), os.environ.get("OPENAI_MODEL", "gpt-5.4-nano"),
                     budget, ".cache/llm")


def hermes_deps() -> dict:
    """Overrides for the [hermes] config table (binary, profile_root, env); tests inject a fake binary here."""
    return {}


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

    mem = getattr(agent, "memory", None)  # an outside agent (Hermes) may have neither; never crash before write
    out = {}
    for s in [getattr(mem, "writer", None), *getattr(mem, "reflectors", []), *(getattr(agent, "retries", None) or [])]:
        if isinstance(s, WriteFilter):
            out["write_filter_fallbacks"] = s.fallbacks
            out["write_filter_dropped_rules"] = s.dropped_rules
        elif isinstance(s, Reflect):
            out["reflect_failures"] = s.failures
        elif isinstance(s, Reflexion):
            out["reflexion_fallbacks"] = s.fallbacks
    return out


def _results_path(results_dir: Path, name: str) -> Path:
    return results_dir / f"simulation_{name}.md"


def _run_simulation(name: str, llm: LLMClient, store_dir: Path, results_dir: Path,
                    per_config_cap: int = PER_CONFIG_CAP) -> SimulationAborted | None:
    """Run one config and write its result; returns the abort, or None when it finished."""
    cfg = load_config(CONFIGS / f"{name}.toml")
    corrections = json.loads((DATA / "corrections.json").read_text(encoding="utf-8"))
    blocklist = json.loads((DATA / "blocklist.json").read_text(encoding="utf-8"))
    tasks = [Task(**json.loads(ln)) for ln in (DATA / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    embedder = make_embedder() if cfg.memory == "naive_rag" else None
    hermes = cfg.agent == "hermes"
    # Hermes keeps its own MEMORY.md (agent.store) and spends llm.budget from its usage file, in its own data root.
    store = None if hermes else Store(store_dir)
    deps = hermes_deps() if hermes else ({"embedder": embedder} if embedder else {})
    agent = build(cfg, llm=llm, store=store, check=sim_check(corrections), **deps)
    try:
        before = llm.budget.used
        extra, aborted = {"per_config_cap": per_config_cap}, None
        if hermes:
            extra |= {"hermes_version": agent.version(), "reproducibility": "not cache-reproducible"}
        else:
            extra["llm_cache"] = CACHE_NOTE
        if "reflexion" in cfg.reflect:
            extra["note"] = REFLEXION_NOTE  # the retry check is the scoring check and the prompt has the rule wording
        try:
            metrics = run_simulation(agent, tasks, SimClock(SIM_START), Reviewer([blocklist["marker"]]),
                                     store=agent.store if hermes else store, corrections=corrections,
                                     blocklist=blocklist)
        except SimulationAborted as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            metrics, aborted = exc.metrics, exc
            crashed = exc.crashed_tokens
            if hermes:  # no LLMClient to price the crashed step: what Hermes spent minus what the weeks hold
                crashed = agent.tokens_used - sum(m.tokens for m in metrics.values())
            extra |= {"partial": True, "completed_tasks": exc.completed_tasks, "crashed_tokens": crashed}
        if hermes:
            extra |= {"memory_size_per_week": {f"week {i}": s for i, s in enumerate(agent.memory_sizes, 1)},
                      "failed_attempts": agent.failed_attempts, "planted_over_cap": agent.planted_over_cap}
        weeks = {f"week {w}": m for w, m in metrics.items()}
        # A whole-memory baseline recalls only the log, and Hermes with memory off loads no MEMORY.md,
        # so the planted rule never reaches their prompt.
        if cfg.memory or (hermes and not agent.memory_enabled):
            weeks = {w: dataclasses.asdict(m) | {"extra_from_wrong_rule": BASELINE_NA} for w, m in weeks.items()}
        path = _results_path(results_dir, name)
        write_result(path, eval_name="simulation", config=name, model=agent.model if hermes else llm.model,
                     embedding_model=embedder.name if embedder else "none", subset=f"all {len(tasks)} tasks",
                     seed=SIM_SEED, tokens=llm.budget.used - before,
                     metrics=weeks,
                     extra={**extra, **_counters(agent)}, run_date=date.today().isoformat())
    finally:
        if hermes:
            agent.close()  # stops the gateway; no Hermes memory or session may outlive the run, whatever happened
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


def _run_lme(args, names: list[str], est, full) -> int:
    """LongMemEval: one shared budget of --max-tokens; a failed config writes a PARTIAL result and stops the run.
    `full` is the estimate of the same configs on the full set (all questions)."""
    if not args.confirm_full and (est.needs_subset or (full.needs_subset and est.total > SUBSET_LIMIT)):
        print(f"refused: the full set is estimated at {full.total:,} (above {SUBSET_THRESHOLD:,}) and this run at "
              f"{est.total:,}. Run a subset under {SUBSET_LIMIT:,} first (fewer --questions or configs), then ask "
              f"before a larger run and pass --confirm-full", file=sys.stderr)
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


def extrapolate(per_task_tokens: list[int], tasks_per_run: int = 40, runs: int = 6) -> dict:
    """Scale the pilot's mean tokens per task to a full run, to `runs` runs, and to one run per config (2 configs)."""
    mean = sum(per_task_tokens) / len(per_task_tokens)
    per_run = round(mean * tasks_per_run)
    return {"mean": mean, "per_run": per_run, "all_runs": per_run * runs, "one_run_per_config": per_run * 2}


PILOT_CAVEATS = [
    "the pilot sends no corrections, plants no wrong rule and starts from an empty MEMORY.md, so the per-task "
    "figure is biased downward against a full 40-task run (memory and prompt grow over the run)",
    "6 runs = per run x 6 assumes hermes_default and hermes_no_memory cost the same; probably not true "
    "(memory off has a shorter prompt), so it is a rough planning number: run the pilot for hermes_no_memory too "
    "if it matters",
    "the token cap is checked after each task, so one task can overshoot it",
    "each Hermes call carries a fixed overhead (its system prompt and tools) even for a short task, measured in the "
    "real pilot (numbers in results/pilot_<config>.md and docs/hermes-flags.md), so a 40-task run needs a cap above "
    "the 100,000 per-config default; the spec allows raising the cap for Hermes only, `run` needs an explicit "
    "`--per-config-cap`",
]


def _pilot_range(text: str) -> int:
    n = int(text)
    if not 1 <= n <= 40:
        raise argparse.ArgumentTypeError(f"must be between 1 and 40, got {n}")
    return n


def _pilot(args, parser) -> int:
    from types import SimpleNamespace

    from agent_memory.methods.hermes import HermesError

    cfg = load_config(CONFIGS / f"{args.config}.toml") if (CONFIGS / f"{args.config}.toml").exists() else None
    if cfg is None or cfg.agent != "hermes":
        print(f"refused: {args.config!r} is not an agent = \"hermes\" config", file=sys.stderr)
        return 2
    opts = cfg.options.get("hermes", {})
    if not args.run:
        host = urlparse(os.environ.get("OPENAI_BASE_URL") or "").hostname or "(Hermes default)"
        print(f"dry run, Hermes was not invoked (pass --run --max-tokens N to run)\n"
              f"config: {args.config}, tasks: first {args.tasks} of 40\n"
              f"model: {opts.get('model', 'gpt-5.4-nano')}, endpoint: {host}, key from env var: {opts.get('key_env')}\n"
              f"data root: HERMES_HOME={opts.get('profile_root', '.hermes-lab/' + args.config)} (reused)\n"
              f"per task: {opts.get('binary', 'hermes')} -z <prompt> --usage-file <file> "
              f"--provider custom -m <model> -t <toolsets>\n{HERMES_BOOTSTRAP_NOTE}")
        return 0
    if args.max_tokens is None:
        print("refused: --run needs --max-tokens (the pilot makes real model calls)", file=sys.stderr)
        return 2
    path = args.results_dir / f"pilot_{args.config}.md"
    if path.exists() and not args.overwrite:
        print(f"refused: {path} exists (pass --overwrite to replace it)", file=sys.stderr)
        return 2
    tasks = [Task(**json.loads(ln)) for ln in (DATA / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
             if ln.strip()][:args.tasks]
    print(HERMES_BOOTSTRAP_NOTE)
    budget = TokenBudget(args.max_tokens)
    agent = build(cfg, llm=SimpleNamespace(budget=budget), store=None, **hermes_deps())
    rows, stopped, error = [], None, None  # row: (task id, tokens, words or None, failed)
    clock = SimClock(SIM_START)
    try:
        version = agent.version()
        for i, task in enumerate(tasks):
            prev = tasks[i - 1] if i else None
            slot = 0 if prev is None or (prev.week, prev.day) != (task.week, task.day) else slot + 1
            clock.set(SIM_START + timedelta(days=(task.week - 1) * 7 + task.day - 1, hours=9 + 2 * slot))
            used, failed = budget.used, agent.failed_attempts
            try:
                out = agent.run_task(task, clock.now())
            except BudgetExceeded as exc:
                rows.append((task.id, budget.used - used, None, True))
                stopped = str(exc)
                break
            rows.append((task.id, budget.used - used, len(out.output.split()), agent.failed_attempts > failed))
    except HermesError as exc:
        error = exc
    finally:
        failed_total = agent.failed_attempts
        agent.close()  # stops the gateway; no Hermes memory or session may outlive the run
    if error:
        print(f"pilot crashed after {len(rows)} tasks: {error}", file=sys.stderr)
        return 1
    ex = extrapolate([r[1] for r in rows])
    print("task, tokens, words, failed")
    for tid, tok, words, bad in rows:
        print(f"{tid}, {tok}, {'n/a' if words is None else words}, {'yes' if bad else 'no'}")
    n = len(rows)
    lines = [f"mean tokens per task: {ex['mean']:.0f}",
             f"40 tasks = {ex['per_run']:,} per run",
             f"6 runs = 2 configs x 3 runs = {ex['all_runs']:,}",
             f"1 run per config (2 configs) = {ex['one_run_per_config']:,}",
             f"per-config cap {PER_CONFIG_CAP:,}: a single run would "
             f"{'exceed' if ex['per_run'] > PER_CONFIG_CAP else 'stay under'} it"]
    if stopped:
        print(f"stopped: token budget reached ({stopped}); partial summary of {n} tasks; "
              f"overshoot: {budget.used - args.max_tokens:,} tokens over the cap")
    print("\n".join(lines))
    print("caveats:\n" + "\n".join(f"- {c}" for c in PILOT_CAVEATS))
    print(f"This is an extrapolation from {n} tasks; nothing beyond the pilot was run. "
          "The user decides before any full Hermes run.")
    extra = {"hermes_version": version, "reproducibility": "not cache-reproducible", "tasks": n,
             "mean_tokens_per_task": f"{ex['mean']:.0f}", "failed_attempts": failed_total,
             "extrapolation_per_run_40_tasks": ex["per_run"], "extrapolation_6_runs": ex["all_runs"],
             "extrapolation_1_run_per_config": ex["one_run_per_config"], "per_config_cap": PER_CONFIG_CAP,
             "caveats": " | ".join(PILOT_CAVEATS)}
    if stopped:
        extra["budget_overshoot"] = budget.used - args.max_tokens
        extra["partial"] = True
    write_result(path, eval_name="pilot", config=args.config, model=agent.model, embedding_model="none",
                 subset=f"first {n} tasks", seed=SIM_SEED, tokens=budget.used,
                 metrics={f"task {t}": {"tokens": tok, "words": w, "failed": bad} for t, tok, w, bad in rows},
                 extra=extra, run_date=date.today().isoformat())
    print(f"wrote {path}")
    return 1 if stopped else 0


def _positive(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


def _run(args, parser) -> int:
    explicit_cap = args.per_config_cap is not None  # Hermes runs must name their cap
    args.per_config_cap = args.per_config_cap or PER_CONFIG_CAP
    names = [n.strip() for n in args.configs.split(",") if n.strip()]
    available = sorted(p.stem for p in CONFIGS.glob("*.toml"))
    if args.eval == "longmemeval":
        available = [n for n in available if n.startswith("lme_")]
    unknown = [n for n in names if n not in available]
    if unknown or not names:
        parser.error(f"unknown config(s): {', '.join(unknown) or '(none given)'}; available: {', '.join(available)}")

    stages = None
    if args.eval == "longmemeval":
        stages = {n: c.memory or c.write for n, c in ((n, load_config(CONFIGS / f"{n}.toml")) for n in names)}
    est = estimate(args.eval, names, args.questions, args.full_context_questions, stages)
    for n, t in est.by_config.items():
        print(f"{n}: {t}")
    print(f"total: {est.total} (prompt {est.prompt}, completion {est.completion}, overhead {est.overhead})")
    print(f"above {SUBSET_THRESHOLD:,}: {'yes' if est.needs_subset else 'no'}")
    if args.eval == "simulation":
        print("note: the simulation per-task numbers are a placeholder (2,000 prompt + 500 completion per task)")
        print(f"per-config cap: {args.per_config_cap:,}")
        if any(n.startswith("hermes") for n in names):
            print("note: Hermes tokens are measured by the pilot, not estimated (priced at 0 here); "
                  "its run stops at the per-config cap using its own usage file")
            print(HERMES_BOOTSTRAP_NOTE)
    else:
        print(LME_NOTE)
    try:
        gate(est, args.max_tokens, args.estimate_only)
    except EstimateOnly:
        print("estimate only, nothing was run (pass --no-estimate-only to run)")
        return 0
    except BudgetExceeded as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if args.eval == "longmemeval":
        return _run_lme(args, names, est, estimate(args.eval, names, None, args.full_context_questions, stages))
    if est.needs_subset:
        print(f"refused: estimate above {SUBSET_THRESHOLD:,}, run a subset first", file=sys.stderr)
        return 2
    # Every refusal below happens before an LLM client is built or a file is written.
    if args.max_tokens is None:
        print("refused: --no-estimate-only needs --max-tokens (the run's total token cap)", file=sys.stderr)
        return 2
    hermes = [n for n in names if load_config(CONFIGS / f"{n}.toml").agent == "hermes"]
    if hermes and not explicit_cap:
        print(f"refused: {', '.join(hermes)} needs an explicit --per-config-cap. The default {PER_CONFIG_CAP:,} "
              "stops a Hermes run before its 40 tasks are done; use at least the per-run figure from the pilot "
              "(results/pilot_<config>.md, a downward-biased lower bound) plus headroom. The spec allows raising "
              "the cap for Hermes only.", file=sys.stderr)
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
        budget = TokenBudget(min(args.per_config_cap, remaining))
        aborted = _run_simulation(n, make_llm(budget), out / n, args.results_dir, args.per_config_cap)
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


_DEMO_LIVE_ENV = ("OPENAI_API_KEY", "EMBEDDING_BASE_URL", "EMBEDDING_MODEL")  # OPENAI_BASE_URL, EMBEDDING_API_KEY optional


def _demo(args, *, transport=None, embed_transport=None, ready=None) -> int:
    """`transport` and `embed_transport` replace the real clients (tests); `ready(server)` is called once serving."""
    from agent_memory.demo.paths import DemoPaths
    from agent_memory.demo.script import estimate_tokens, run_script
    from agent_memory.demo.server import make_server
    from agent_memory.demo.session import Session

    try:
        paths = DemoPaths(args.data_dir) if args.data_dir else DemoPaths(DEMO_DEFAULT_ROOT)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"estimated tokens: {estimate_tokens(include_second_act=True):,} (placeholder, unverified until a real warm-up)")
    print(f"data dir: {paths.root}")
    if args.estimate_only:
        return 0
    mode = "warmup" if args.warmup else args.mode
    if mode != "replay":
        missing = [v for v in _DEMO_LIVE_ENV if not os.environ.get(v)
                   and not (v == "OPENAI_API_KEY" and transport) and not (v != "OPENAI_API_KEY" and embed_transport)]
        if missing:
            print(f"error: set {', '.join(missing)} in the environment first", file=sys.stderr)
            return 2
    session = Session(paths, mode=mode, max_tokens=args.max_tokens, base_url=os.environ.get("OPENAI_BASE_URL"),
                      model=os.environ.get("OPENAI_MODEL", "gpt-5.4-nano"), config_dir=CONFIGS / "demo",
                      transport=transport, embed_transport=embed_transport)
    if args.warmup:
        run_script(session, include_second_act=True)
        cols = session.snapshot()["columns"]
        print(f"warm-up tokens used: {sum(c['tokens'] for c in cols.values()):,}")
        errors = [f"{n}: {c['error']}" for n, c in cols.items() if c["error"]]
        if errors:
            print("warm-up errors: " + "; ".join(errors), file=sys.stderr)
            return 1
        return 0
    server = make_server(session, args.port)
    print(f"http://127.0.0.1:{server.server_address[1]}/")
    if ready:
        ready(server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None, *, demo_transport=None, demo_embed_transport=None,
         demo_ready=None) -> int:
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
        "required with --no-estimate-only: the run's total token cap. Each config also gets its own cap of "
        "min(--per-config-cap, what is left of the total). A config that hits its cap writes a PARTIAL result "
        "and the run goes on with the next config; the run stops once the total is spent or a config "
        "crashes for any other reason. Any partial result makes the exit code 1. On longmemeval the cap is one "
        "budget shared by all configs, and the first config that hits it writes a PARTIAL result and ends the run."))
    run.add_argument("--per-config-cap", type=_positive, default=None, help=(
        f"simulation: each config's own token cap (default {PER_CONFIG_CAP:,}, the spec's limit). Raising it is a "
        "decision to take after a pilot run shows a config needs more. Required (explicit) for Hermes configs"))
    run.add_argument("--questions", type=_positive, help=(
        "longmemeval: run only the first N selected questions, stratified evenly over the abilities "
        "(e.g. 8 for the subset run under 1,000,000 tokens)"))
    run.add_argument("--full-context-questions", type=int, default=10,
                     help="longmemeval: questions for lme_baseline_full_context (default 10)")
    run.add_argument("--download", action="store_true",
                     help="longmemeval: download the dataset into .cache/ if it is missing (the only network fetch)")
    run.add_argument("--confirm-full", action="store_true", help=(
        "longmemeval: when the full set (50 questions) is estimated above 5,000,000, a run estimated above "
        "1,000,000 is refused without this flag. Global rule: run a subset under 1,000,000 first (--questions), "
        "then ask the user before a larger run"))
    run.add_argument("--overwrite", action="store_true", help="replace existing results files")
    run.add_argument("--out", type=Path, help="where the per-config stores go (default: a temp dir)")
    run.add_argument("--results-dir", type=Path, default=Path("results"))
    pilot = sub.add_parser("pilot", help="run the first N tasks on a Hermes config and extrapolate the tokens")
    pilot.add_argument("--config", default="hermes_default")
    pilot.add_argument("--tasks", type=_pilot_range, default=3, help="first N tasks, 1 to 40 (default 3)")
    pilot.add_argument("--run", action="store_true", help="really call Hermes and the model (default: dry run)")
    pilot.add_argument("--max-tokens", type=_positive, help="required with --run: stop when Hermes' usage passes it")
    pilot.add_argument("--overwrite", action="store_true", help="replace an existing pilot results file")
    pilot.add_argument("--results-dir", type=Path, default=Path("results"))
    demo = sub.add_parser("demo", help="local side-by-side chat demo: no memory vs full memory")
    demo.add_argument("--port", type=int, default=8765)
    demo.add_argument("--max-tokens", type=_positive, default=100_000, help="token cap per column")
    demo.add_argument("--mode", choices=["live", "replay"], default="live")
    demo.add_argument("--data-dir", type=Path, help="default: .demo/ in the repo")
    demo.add_argument("--warmup", action="store_true", help="run the scripted story live once to fill the replay cache")
    demo.add_argument("--estimate-only", action="store_true", help="print the estimate and the data dir, then stop")
    args = parser.parse_args(argv)
    if args.command == "demo":
        return _demo(args, transport=demo_transport, embed_transport=demo_embed_transport, ready=demo_ready)
    if args.command == "pilot":
        import agent_memory.methods  # noqa: F401

        return _pilot(args, pilot)
    if args.command == "run":
        import agent_memory.methods  # noqa: F401  registers the stages before load_config/build

        return _run(args, run)
    if not args.store.is_dir():
        parser.error(f"no store at {args.store}")  # Store() would create an empty one
    print("\n".join(rules_diff(Store(args.store), args.start, args.end)))
    return 0
