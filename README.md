<div align="center">

# agent-memory

**A private lab that measures agent-memory techniques by config-driven ablation.**

![python](https://img.shields.io/badge/python-3.11%2B-blue) ![license](https://img.shields.io/badge/license-MIT-green) ![version](https://img.shields.io/badge/version-0.1.0-lightgrey) ![status](https://img.shields.io/badge/results-none%20yet-orange)

[Pipeline](#pipeline) | [Quickstart](#quickstart) | [Methods](#methods) | [Configs](#configs) | [Results](#results) | [Caveats](#caveats) | [Backlog](#backlog)

</div>

Each technique from the tweet "Memory Engineering: How to Build an Agent That Gets Smarter Every Day" (@distortgeekin, 2026-11-16) is a runnable stage in its own folder: write, sort, recall, reflect, forget, reflexion. Stages are switched on and off by TOML config, so the same code gives baselines, a build-up chain and leave-one-out runs. The goal is to find out, with our own measurements, which parts of the recipe help. It is a lab to read and run, not a memory service or an SDK.

| At a glance | |
|---|---|
| Evals | 2: a simulated 4-week email follow-up agent (40 tasks), and LongMemEval |
| Method folders | 14 under `src/agent_memory/methods/`, each with its own README |
| Configs | 20: 14 for the simulation, 6 `lme_*` for LongMemEval |
| Store layout | one fixed layout (RULES, FACTS, LOG) shared by every stage |

## Pipeline

<p align="center"><img src="docs/diagrams/pipeline.svg" alt="The six stage kinds, in the tweet's order: write, sort, recall, reflect, forget, reflexion (drawn as five boxes: reflect and forget share one). In a run, each task does recall, answer, an optional reflexion retry, then write and forget; reflect runs on Fridays. The store holds RULES, FACTS and LOG." width="100%"></p>

The six stage kinds, in the tweet's order: write, sort, recall, reflect, forget, reflexion (drawn as five boxes: reflect and forget share one). In a run, each task does recall, answer, an optional reflexion retry, then write and forget; reflect runs on Fridays. The diagram shows stage kinds, not run order.

Every stage-based memory uses the same store: RULES (always loaded, 20 lines at most), FACTS (one entry per key, newest wins) and LOG (dated events, searched only when needed). Every stage gets `now` from outside; nothing in `core/` or `methods/` reads system time.

## Quickstart

Prerequisites: Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run agent-memory run --eval simulation --configs full --estimate-only
```

The last command makes no LLM call. Output today:

```
full: 100000
total: 100000 (prompt 80000, completion 20000, overhead 0)
above 5,000,000: no
note: the simulation per-task numbers are a placeholder (2,000 prompt + 500 completion per task)
estimate only, nothing was run (pass --no-estimate-only to run)
```

`--estimate-only` is the default for `run`. A real run needs `--no-estimate-only`, an `OPENAI_API_KEY` (see `.env.example`) and a token cap with `--max-tokens`.

Hermes pilot (a dry run unless `--run --max-tokens N` is given; `--run` makes real model calls): `uv run agent-memory pilot --config hermes_default --tasks 3` prints tokens per task and the extrapolation to 40 tasks x 6 runs.

<details>
<summary>More commands</summary>

Estimate the whole simulation matrix (14 configs):

```bash
uv run agent-memory run --eval simulation --configs baseline_full_context,baseline_naive_rag,b1_write_filter,b2_coala_stores,b3_recall,b4_reflect,b5_forget,full,no_write_filter,no_coala_stores,no_recall,no_reflect,no_forget,no_reflexion --estimate-only
```

Estimate a LongMemEval subset (no download, no LLM call):

```bash
uv run agent-memory run --eval longmemeval --configs lme_full --questions 8 --estimate-only
```

Print the RULES diff between two points in time for a store left by a run (`--out` sets where stores go):

```bash
uv run agent-memory review diff --store <out>/<config> --from 2026-01-05T00:00:00 --to 2026-01-12T00:00:00
```

On an empty store directory this prints only the two header lines.

</details>

## Methods

Each method has its own README with constants, behavior and an example.

| Folder | Part | What it does |
|---|---|---|
| [`full_context`](src/agent_memory/methods/full_context/README.md) | baseline | whole history in the prompt |
| [`naive_rag`](src/agent_memory/methods/naive_rag/README.md) | baseline | embed past turns, retrieve top-k by similarity |
| [`write_filter`](src/agent_memory/methods/write_filter/README.md) | write | store lessons, decisions, preferences and results as one line each; never transcripts |
| [`coala_stores`](src/agent_memory/methods/coala_stores/README.md) | sort | RULES / FACTS / LOG routing (working memory is the context itself) |
| [`tag_recall`](src/agent_memory/methods/tag_recall/README.md) | recall | RULES plus FACTS whose tag matches the task, LOG only on request |
| [`scored_recall`](src/agent_memory/methods/scored_recall/README.md) | recall | recency x importance x relevance, as in Generative Agents |
| [`reflect`](src/agent_memory/methods/reflect/README.md) | reflect | turn new LOG lines into at most 3 rules, archive those lines |
| [`overwrite`](src/agent_memory/methods/overwrite/README.md) | forget | a new fact replaces the old one in place |
| [`expire`](src/agent_memory/methods/expire/README.md) | forget | one-off notes get a date and disappear after 7 days |
| [`archive`](src/agent_memory/methods/archive/README.md) | forget | rules not fired in 30 days leave the always-loaded file |
| [`reflexion`](src/agent_memory/methods/reflexion/README.md) | reflect | one retry after a failed check, with a reflection note that is also written to memory |

Defaults used when a config leaves a part out: [`write_raw`](src/agent_memory/methods/write_raw/README.md) (write), [`pool_route`](src/agent_memory/methods/pool_route/README.md) (sort) and [`rules_only`](src/agent_memory/methods/rules_only/README.md) (recall).

The Hermes Agent baseline is built (see its [README](src/agent_memory/methods/hermes/README.md) and [Caveats](#caveats)).

## Configs

One TOML file per config in [`configs/`](configs/README.md). `no_reflexion` is identical to `b5_forget`, so it is a duplicate, not a second run.

| Group | Configs (simulation) |
|---|---|
| Baselines | `baseline_full_context`, `baseline_naive_rag` |
| Build-up chain | `b1_write_filter`, `b2_coala_stores`, `b3_recall`, `b4_reflect`, `b5_forget`, `full` |
| Leave-one-out from `full` | `no_write_filter`, `no_coala_stores`, `no_recall`, `no_reflect`, `no_forget`, `no_reflexion` |

| Group | Configs (LongMemEval) |
|---|---|
| Baselines | `lme_baseline_full_context`, `lme_baseline_naive_rag` |
| Build-up chain | `lme_b1_write_filter`, `lme_b2_coala_stores`, `lme_b3_scored_recall`, `lme_full` |

On LongMemEval only `overwrite` runs as a forget stage; `reflect`, `reflexion`, `expire` and `archive` do not run there. Details are in [`configs/README.md`](configs/README.md).

## Results

**No results yet.** The first runs need the user's go-ahead and a token budget, so there is no results table and no `results/` folder. When runs exist, each writes `results/<eval>_<config>.md` with a fixed header (date, model, embedding model, subset, seed, tokens) and the tables here will link to those files.

The corrections-per-week figure below is an empty template, not a chart. It will be filled by the first measured runs.

<p align="center"><img src="docs/diagrams/corrections-per-week.svg" alt="Empty axes for corrections per week, labelled no data yet" width="70%"></p>

Estimates from the dry runs (no LLM call was made):

| Eval | Estimate | Note |
|---|---|---|
| Simulation, 1 config | 100,000 tokens | placeholder: 2,000 prompt + 500 completion per task, 40 tasks |
| Simulation, 14 configs | 1,400,000 tokens (prompt 1,120,000, completion 280,000) | same placeholder; not above 5,000,000 |
| LongMemEval, `lme_full`, `--questions 8` | 967,200 tokens (prompt 920,000, completion 24,000, overhead 23,200) | per-question overheads are UNVERIFIED placeholders; not above 5,000,000 |

For LongMemEval the full set is above 5,000,000 tokens. The rule is to run a subset under 1,000,000 first and ask before the full set. The CLI enforces it: when the full-set estimate of the chosen configs is above 5,000,000, a run estimated above 1,000,000 is refused unless `--confirm-full` is given.

## Caveats

- The tweet's numbers (91% HumanEval for Reflexion, 39% and 84% for Anthropic's memory tool and context editing, corrections per week 14, 9, 4, 1) are the author's claims. They are NOT verified and are not reproduced here.
- `archive` cannot fire in the 28-day simulation, because a rule cannot be 30 days old in a 28-day run (`last_used_at` starts at creation) and the recall stages always render rules.
- `overwrite` is close to a no-op after `write_filter`: facts are already collapsed at write time by `upsert_fact`.
- Under `expire`, the `reflect` stage effectively has a 7-day window. Under `write_raw`, corrections expire after 7 days while `write_filter` turns them into rules, so part of any `no_write_filter` gap under `expire` is this artifact.
- Reflexion is told the failed check and the rule wording, so the check acts as an oracle, stronger than a real deployment.
- The LongMemEval judge is the LLM judge copied from LongMemEval's `evaluate_qa.py`, run on `gpt-5.4-nano`. It is NOT comparable with the official GPT-4o judge.
- `lme_b1_write_filter` and `lme_b2_coala_stores` recall an empty memory (a no-memory floor), so abstention scores high.
- The LongMemEval date format and the placeholder token overheads are UNVERIFIED until the first real download and run.
- The simulation token estimate is a placeholder until a measured run.
- Each simulation config is capped at 100,000 tokens (the spec's limit). A stub run used about 147,000 for `baseline_full_context`, so some configs may stop with a PARTIAL result. `--per-config-cap N` raises the cap; take that decision after a pilot run.
- `write_filter` handles each distinct correction text until it reaches a rule outcome (stored, duplicate or dropped at the cap). After that, the same correction written again (after a violation) makes no LLM call, so reworded copies cannot fill the 20-rule cap. Rules skipped because 20 are already active are counted as `write_filter_dropped_rules` in the results.
- `extra_from_wrong_rule` is shown as `n/a` for the `full_context` and `naive_rag` baselines: they recall only the log, so the planted rule never reaches their prompt.
- For configs with `reflexion`, the results say that corrections are counted after an oracle-guided retry. Compare memory methods on `first_attempt_failures`.
- The LLM cache key is (model, messages), without the endpoint. Changing `OPENAI_BASE_URL` while keeping the same model name replays cached replies.
- Embedding calls are not counted against the token budgets. With no `EMBEDDING_*` env set, the fastembed model is downloaded from Hugging Face on first use, outside the `--download` gate.
- The Hermes Agent baseline (`hermes_default`, `hermes_no_memory`, simulation only) is built but has no full-run results yet. Its rows are marked "not cache-reproducible", because Hermes calls the model itself and reads real time. Measured on 2026-11-17 by the second real pilot (3 tasks of `hermes_default`, toolsets `memory,todo`): 3,715 / 3,719 / 3,758 tokens per task (mean 3,731), 0 failed attempts; extrapolated 149,227 per 40-task run, 895,362 for 6 runs (2 configs x 3), 298,454 for 1 run per config. The recommended per-config cap for a Hermes run is at least about 150,000 plus headroom for growth: the figure is a downward-biased lower bound (no corrections, no planted rule, empty MEMORY.md). `run` needs an explicit `--per-config-cap` for a Hermes config.

## Data and attribution

- LongMemEval: [`xiaowu0162/longmemeval-cleaned`](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned), MIT. The judge prompts are copied from the LongMemEval repo, `src/evaluation/evaluate_qa.py`. The dataset is downloaded into `.cache/` only with `--download` and is never committed. Sizes (measured 2026-11-17): `longmemeval_s_cleaned.json` 277,383,467 bytes, `longmemeval_oracle.json` 15,388,478 bytes. The download is size-checked, retried up to 3 times and recorded in a `<name>.size` sidecar; a truncated cached file is fetched again.
- LoCoMo is not used (CC BY-NC 4.0).
- The simulation task stream, corrections and blocklist are committed in [`data/simulation/`](data/simulation).

## Backlog

`skill_library` (Voyager), `memgpt_paging`, Anthropic memory tool plus context editing, LoCoMo, a Vietnamese simulation, poisoning through a misread instruction, a `semantic_cache` stage, an orchestrator-workers pattern in the simulation, `hermes_no_review`, Hermes with an external memory provider, Hermes on LongMemEval. Leave-one-out on LongMemEval is also backlog.

See [CHANGELOG.md](CHANGELOG.md).

## License

Code: [MIT](LICENSE). The repo is private; going public is a separate decision.
