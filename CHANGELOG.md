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

### Not yet

- Hermes Agent baseline (adapter, pilot and configs).
- First measured results.
