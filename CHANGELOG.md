# Changelog

## v0.1.0 - 2026-11-17

### Added

- Repo scaffold.
- Core: clock, store layout (RULES, FACTS, LOG), LLM client with token budget, embedder with disk cache, TOML config loading, stage registry and token estimator.
- Simulation runner for the 4-week email follow-up agent (40 tasks) with a scripted reviewer.
- Baselines: `full_context` and `naive_rag`.
- Nine stages: `write_filter`, `coala_stores`, `tag_recall`, `scored_recall`, `reflect`, `overwrite`, `expire`, `archive`, `reflexion`, each with its own README.
- 14 simulation configs and 6 LongMemEval (`lme_*`) configs.
- `agent-memory run` (estimate-only by default) and `agent-memory review diff` CLIs.
- Results writer with a fixed header.
- LongMemEval data loading and runner.
- README with hand-drawn SVG diagrams.
- `--per-config-cap` option for simulation runs (default 100,000).
- `write_filter` skips a correction text it has already handled and counts rules dropped at the 20-rule cap.
- Results show `extra_from_wrong_rule` as `n/a` for whole-memory baselines and note that `reflexion` corrections come after an oracle-guided retry.
- `agent-memory pilot`: runs the first N tasks on a Hermes config (dry run unless `--run --max-tokens N`) and extrapolates tokens to 40 tasks x 6 runs.
- LongMemEval subset-first rule enforced: above 5,000,000 for the full set, a run above 1,000,000 needs `--confirm-full`.

### Not yet

- Hermes Agent baseline (adapter, pilot and configs).
- First measured results.
