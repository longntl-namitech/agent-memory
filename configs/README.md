# Configs

One TOML file per ablation config: 2 baselines, the build-up chain `b1_write_filter` to `full`, and leave-one-out from `full`.

`no_reflexion` is identical to `b5_forget` (`full` is `b5_forget` plus `reflexion`). One of them is a duplicate, not a second run.

## LongMemEval configs (`lme_*`)

Six configs run on LongMemEval: the baselines `lme_baseline_full_context` and `lme_baseline_naive_rag`, and the build-up chain `lme_b1_write_filter`, `lme_b2_coala_stores` (+ `coala_stores`), `lme_b3_scored_recall` (+ `scored_recall`), `lme_full` (+ the `overwrite` forget stage). `lme_full` is the spec's `full_lme`. Leave-one-out is backlog on this eval.

- Cadence: `reflect`, `reflexion`, `expire` and `archive` never run here; a config that lists them, or an `agent` (Hermes), is refused. Only `overwrite` runs, after each session.
- `lme_baseline_full_context` runs on `--full-context-questions` questions (default 10).
- Ingestion LLM calls are cached on disk by (model, messages), so configs with the same write stage pay ingestion once.
- Judge: one yes/no call per question on the same model (`gpt-5.4-nano`), with prompts in the style of the LongMemEval judge. The official judge is GPT-4o, so these scores are NOT comparable with the official leaderboard.
- Cost: the full set is above 5,000,000 tokens. The global rule is: run a subset under 1,000,000 first (`--questions 8`), then ask the user before the full set, which needs `--confirm-full`. The dataset is downloaded only with `--download`.

```
agent-memory run --eval longmemeval --configs lme_full --questions 8               # estimate only
agent-memory run --eval longmemeval --configs lme_full --questions 8 --download \
  --no-estimate-only --max-tokens 1000000
```
