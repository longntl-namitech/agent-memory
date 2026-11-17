# Changelog

## v0.1.0 - 2026-11-17

### Fixed

- LongMemEval download: verify the byte count against the server size, retry a truncated fetch up to 3 times, write a `<name>.size` sidecar, re-fetch an existing truncated file, and make `load_selected` raise a clear `ValueError` on a corrupt cached file.

### Added

- First measured results in `results/`: simulation for 14 lab + 2 Hermes configs, LongMemEval 8-question subset for all 6 configs (`lme_b1_write_filter`, `lme_b2_coala_stores`, `lme_b3_scored_recall`, `lme_full`, `lme_baseline_naive_rag`, `lme_baseline_full_context`).
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
- Hermes Agent baseline: adapter and two configs (`hermes_default`, `hermes_no_memory`), each with its own reused Hermes data root.
- Hermes pilot numbers: measured on 2026-11-17 by the second real pilot (3 tasks of `hermes_default`, toolsets `memory,todo`): 3,715 / 3,719 / 3,758 tokens per task (mean 3,731), 0 failed attempts; extrapolated 149,227 per 40-task run, 895,362 for 6 runs (2 configs x 3), 298,454 for 1 run per config. The recommended per-config cap for a Hermes run is at least about 150,000 plus headroom for growth: the figure is a downward-biased lower bound (no corrections, no planted rule, empty MEMORY.md).
- LongMemEval subset-first rule enforced: above 5,000,000 for the full set, a run above 1,000,000 needs `--confirm-full`.

### Not yet

- The 3-run spread for Hermes.
- The full 50-question LongMemEval run.
- A per-config pass over more seeds.
